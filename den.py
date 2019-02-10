import torch
import torch.nn as nn
from torch.autograd import Variable

from torchvision.models import resnet152
import torchvision.models


class Flatten(nn.Module):
    def __init__(self):
        super(Flatten, self).__init__()

    def forward(self, input):
        return input.view(input.size()[0], -1)


class AuxConv(nn.Module):
    def __init__(self, in_channels, c_tag, stride=1, p=0):
        super(AuxConv, self).__init__()
        self.aux = nn.Sequential(nn.Conv2d(in_channels, c_tag, kernel_size=(3, 1)),
                                 nn.ReLU(),
                                 nn.Dropout(p),
                                 nn.Conv2d(c_tag, c_tag, kernel_size=(1, 3)),
                                 nn.ReLU(),
                                 nn.Dropout(p),
                                 Flatten())

    def forward(self, input):
        return self.aux(input)


class DEN(nn.Module):
    def __init__(self, wts_file, as_feature_extractor=True, p=0):
        super(DEN, self).__init__()

        resnet = resnet152(pretrained=False)
        resnet = self._init_resnet(resnet, wts_file)
        
        if as_feature_extractor:
            for param in resnet.parameters():
                param.requires_grad = False
            
        
        # prepare the network
        self._flat_resnet152(resnet)

        aux_1024 = [AuxConv(in_channels=1024, c_tag=8, p=p) for _ in range(16)]
        aux_2048 = [AuxConv(in_channels=2048, c_tag=64, p=p) for _ in range(3)]
        self.aux_modules = nn.ModuleList(aux_1024 + aux_2048)
    
    def _init_resnet(self, resnet, wts_file):
        resnet.fc = nn.Linear(2048, 25 * 32)
        resnet.load_state_dict(torch.load(wts_file))

        return resnet


    def _flat_resnet152(self, model):
        
        # break the resent to its building blocks
        # into a list
        flattened = []
        flattened += list(model.children())[:4]

        for i in range(4,8):
            sequence = list(model.children())[i]
            flattened += list(sequence.children())

        flattened += list(model.children())[-2:]

        self.resnet_top = nn.Sequential(*flattened[:35])
        self.intermediate_blocks = nn.ModuleList(flattened[35:54])
        self.avg_pool2d = flattened[54]
        self.fc = nn.Linear(25280, 25 * 32)
     
    
    def forward(self, input):
        
        x = self.resnet_top(input)
        
        outputs = []
        for i, block in enumerate(self.intermediate_blocks):
            x = block(x)
            outputs.append(self.aux_modules[i](x))
            
        x = self.avg_pool2d(x)
        x = x.view(x.shape[0], -1)
        outputs.append(x)
        outputs_concat = torch.cat(outputs, dim=1)
        out = self.fc(outputs_concat)

        return out