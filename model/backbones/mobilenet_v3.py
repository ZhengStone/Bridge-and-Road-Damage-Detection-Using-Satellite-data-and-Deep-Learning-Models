'''MobileNetV3 in PyTorch.

See the paper "Inverted Residuals and Linear Bottlenecks:
Mobile Networks for Classification, Detection and Segmentation" for more details.
'''
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import init
from ..bricks import SE


class hswish(nn.Module):
    def forward(self, x):
        out = x * F.relu6(x + 3, inplace=True) / 6
        return out


class hsigmoid(nn.Module):
    def forward(self, x):
        out = F.relu6(x + 3, inplace=True) / 6
        return out


class Block(nn.Module):
    '''expand + depthwise + pointwise'''

    def __init__(self, kernel_size, in_size, expand_size, out_size, nolinear, SE, stride):
        super(Block, self).__init__()
        self.stride = stride
        self.se = SE

        self.conv1 = nn.Conv2d(in_size, expand_size, kernel_size=1, stride=1, padding=0, bias=False)
        self.bn1 = nn.BatchNorm2d(expand_size)
        self.nolinear1 = nolinear
        self.conv2 = nn.Conv2d(expand_size, expand_size, kernel_size=kernel_size, stride=stride,
                               padding=kernel_size // 2, groups=expand_size, bias=False)
        self.bn2 = nn.BatchNorm2d(expand_size)
        self.nolinear2 = nolinear
        self.conv3 = nn.Conv2d(expand_size, out_size, kernel_size=1, stride=1, padding=0, bias=False)
        self.bn3 = nn.BatchNorm2d(out_size)

        self.shortcut = nn.Sequential()
        if stride == 1 and in_size != out_size:
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_size, out_size, kernel_size=1, stride=1, padding=0, bias=False),
                nn.BatchNorm2d(out_size),
            )

    def forward(self, x):
        out = self.nolinear1(self.bn1(self.conv1(x)))
        out = self.nolinear2(self.bn2(self.conv2(out)))
        out = self.bn3(self.conv3(out))
        if self.se != None:
            out = self.se(out)
        out = out + self.shortcut(x) if self.stride == 1 else out
        return out


class MobileNetV3(nn.Module):
    """
    224*224 input
    small:
    0 torch.Size([2, 16, 56, 56])
    1 torch.Size([2, 24, 28, 28])
    2 torch.Size([2, 48, 14, 14])
    3 torch.Size([2, 576, 7, 7])
    large:
    0 torch.Size([2, 24, 56, 56])
    1 torch.Size([2, 40, 28, 28])
    2 torch.Size([2, 160, 14, 14])
    3 torch.Size([2, 960, 7, 7])
    """

    def __init__(self, is_large=False, in_channels=3, out_indices=(0, 1, 2, 3)):
        super(MobileNetV3, self).__init__()
        self.is_large = is_large
        self.out_indices = out_indices
        self.conv1 = nn.Conv2d(in_channels, 16, kernel_size=3, stride=2, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(16)
        self.hs1 = hswish()
        if is_large:
            self.bneck = nn.Sequential(
                Block(3, 16, 16, 16, nn.ReLU(inplace=True), None, 1),
                Block(3, 16, 64, 24, nn.ReLU(inplace=True), None, 2),
                Block(3, 24, 72, 24, nn.ReLU(inplace=True), None, 1),
                Block(5, 24, 72, 40, nn.ReLU(inplace=True), SE(40), 2),
                Block(5, 40, 120, 40, nn.ReLU(inplace=True), SE(40), 1),
                Block(5, 40, 120, 40, nn.ReLU(inplace=True), SE(40), 1),
                Block(3, 40, 240, 80, hswish(), None, 2),
                Block(3, 80, 200, 80, hswish(), None, 1),
                Block(3, 80, 184, 80, hswish(), None, 1),
                Block(3, 80, 184, 80, hswish(), None, 1),
                Block(3, 80, 480, 112, hswish(), SE(112), 1),
                Block(3, 112, 672, 112, hswish(), SE(112), 1),
                Block(5, 112, 672, 160, hswish(), SE(160), 1),
                Block(5, 160, 672, 160, hswish(), SE(160), 2),
                Block(5, 160, 960, 160, hswish(), SE(160), 1),
            )
            self.conv2 = nn.Conv2d(160, 960, kernel_size=1, stride=1, padding=0, bias=False)
            self.bn2 = nn.BatchNorm2d(960)
            self.linear3 = nn.Linear(960, 1280)
            self.feature_idx_list = [2, 5, 12, -1]
        else:
            self.bneck = nn.Sequential(
                Block(3, 16, 16, 16, nn.ReLU(inplace=True), SE(16), 2),
                Block(3, 16, 72, 24, nn.ReLU(inplace=True), None, 2),
                Block(3, 24, 88, 24, nn.ReLU(inplace=True), None, 1),
                Block(5, 24, 96, 40, hswish(), SE(40), 2),
                Block(5, 40, 240, 40, hswish(), SE(40), 1),
                Block(5, 40, 240, 40, hswish(), SE(40), 1),
                Block(5, 40, 120, 48, hswish(), SE(48), 1),
                Block(5, 48, 144, 48, hswish(), SE(48), 1),
                Block(5, 48, 288, 96, hswish(), SE(96), 2),
                Block(5, 96, 576, 96, hswish(), SE(96), 1),
                Block(5, 96, 576, 96, hswish(), SE(96), 1),
            )
            self.conv2 = nn.Conv2d(96, 576, kernel_size=1, stride=1, padding=0, bias=False)
            self.bn2 = nn.BatchNorm2d(576)
            self.linear3 = nn.Linear(576, 1280)
            self.feature_idx_list = [0, 2, 7, -1]

        self.hs2 = hswish()
        self.bn3 = nn.BatchNorm1d(1280)
        self.hs3 = hswish()
        self.init_params()

    def init_params(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                init.kaiming_normal_(m.weight, mode='fan_out')
                if m.bias is not None:
                    init.constant_(m.bias, 0)
            elif isinstance(m, nn.BatchNorm2d):
                init.constant_(m.weight, 1)
                init.constant_(m.bias, 0)
            elif isinstance(m, nn.Linear):
                init.normal_(m.weight, std=0.001)
                if m.bias is not None:
                    init.constant_(m.bias, 0)

    def forward(self, x):
        out = self.hs1(self.bn1(self.conv1(x)))
        # out = self.bneck(out)
        out_list = []
        for block in self.bneck:
            out = block(out)
            out_list.append(out)
        out = self.hs2(self.bn2(self.conv2(out)))
        out_list.append(out)
        feature = [out_list[i] for i in self.feature_idx_list]
        return [feature[i] for i in self.out_indices]
