import os
import torch
from torch import optim
from torch.optim.lr_scheduler import StepLR
from torch import nn
from torch.nn import functional as F

from tvae.data.mnist import Preprocessor
from tvae.containers.tvae import TVAE
from tvae.models.mlp import MLP_Decoder_w_WN_Tanh, MLP_Encoder_w_WN, MLP_Decoder_w_WN, MLP_Encoder, MLP_Decoder
from tvae.models.fc import FC_Encoder_w_WN, FC_Decoder_w_WN, FC_Encoder, FC_Decoder
from tvae.containers.encoder import Gaussian_Encoder
from tvae.containers.decoder import Bernoulli_Decoder, Gaussian_Decoder
from tvae.containers.grouper import Chi_Squared_from_Gaussian_2d, Gaussian_2d_Test
from tvae.utils.logging import configure_logging, get_dirs
from tvae.utils.train_loops import train_epoch, eval_epoch
from torch.nn.utils import weight_norm as wn


def create_model(n_caps, cap_dim, group_kernel, mu_init):
    s_dim = n_caps * cap_dim
    z_encoder = Gaussian_Encoder(nn.Sequential(
                                            #  wn(
                                             nn.Conv2d(1, s_dim*2,
                                             kernel_size=28, stride=1, padding=0)
                                            #  )
                                             ),
                                 loc=0.0, scale=1.0)

    u_encoder = Gaussian_Encoder(nn.Sequential(
                                            #  wn(
                                             nn.Conv2d(1, s_dim*2,
                                             kernel_size=28, stride=1, padding=0)
                                            #  )
                                             ),                                
                                 loc=0.0, scale=1.0)

    decoder = Bernoulli_Decoder(nn.Sequential(
                # wn(
                nn.ConvTranspose2d(s_dim, 1, 
                    kernel_size=28, stride=1, padding=0)
                # )
                , nn.Sigmoid()
                ))

    grouper = Gaussian_2d_Test(nn.ConvTranspose3d(in_channels=1, out_channels=1,
                                          kernel_size=group_kernel, 
                                          padding=(2*(group_kernel[0] // 2), 
                                                   2*(group_kernel[1] // 2),
                                                   2*(group_kernel[2] // 2)),
                                          stride=(1,1,1), padding_mode='zeros', bias=False),
                      lambda x: F.pad(x, (group_kernel[2] // 2, group_kernel[2] // 2,
                                          group_kernel[1] // 2, group_kernel[1] // 2,
                                          group_kernel[0] // 2, group_kernel[0] // 2), 
                                          mode='circular'),
                       n_caps=n_caps, cap_dim=cap_dim,
                       mu_init=mu_init)
    
    return TVAE(z_encoder, u_encoder, decoder, grouper)


def main():
    config = {
        'wandb_on': True,
        'lr': 1e-3,
        'momentum': 0.9,
        'batch_size': 128,
        'max_epochs': 100,
        'eval_epochs': 5,
        'dataset': 'MNIST',
        'train_angle_set': '0',
        'test_angle_set': '0',
        'train_color_set': "0",
        'test_color_set': "0",
        'train_scale_set': "1",
        'test_scale_set': "1",
        'pct_val': 0.2,
        'random_crop': 28,
        'seed': 1,
        'n_caps': 1,
        'cap_dim': 18*18,
        'mu_init': 30.0,
        'n_is_samples': 10,
        # 'normalize': True, # Not implemented
        # 'whiten': False
        }

    # if config['normalize']: raise NotImplementedError

    name = 'TVAE-2D_18x18_MNIST_L=0_K=5x5_1LayerFC_T=z+mu/sqrt(WU**2)_1e-3_NoWN_mu30'
    config['savedir'], config['data_dir'], config['wandb_dir'] = get_dirs()

    savepath = os.path.join(config['savedir'], name)
    preprocessor = Preprocessor(config)
    train_loader, val_loader, test_loader = preprocessor.get_dataloaders(batch_size=config['batch_size'])

    model = create_model(n_caps=config['n_caps'], cap_dim=config['cap_dim'], group_kernel=(5,5,1), mu_init=config['mu_init'])
    model.to('cuda')
    
    log, checkpoint_path = configure_logging(config, name, model)
    # model.load_state_dict(torch.load(load_checkpoint_path))

    optimizer = optim.SGD(model.parameters(), 
                           lr=config['lr'],
                           momentum=config['momentum'])
    scheduler = StepLR(optimizer, step_size=1, gamma=1.0)

    for e in range(config['max_epochs']):
        log('Epoch', e)

        total_loss, total_neg_logpx_z, total_kl, total_eq_loss, num_batches = train_epoch(model, optimizer, 
                                                                     train_loader, log,
                                                                     savepath, e, eval_batches=300,
                                                                     plot_weights=False,
                                                                     plot_fullcaptrav=False,
                                                                     wandb_on=config['wandb_on'])

        log("Epoch Avg Loss", total_loss / num_batches)
        log("Epoch Avg -LogP(x|z)", total_neg_logpx_z / num_batches)
        log("Epoch Avg KL", total_kl / num_batches)
        log("Epoch Avg EQ Loss", total_eq_loss / num_batches)
        scheduler.step()

        torch.save(model.state_dict(), checkpoint_path)

        if e % config['eval_epochs'] == 0:
            total_loss, total_neg_logpx_z, total_kl, total_is_estimate, total_eq_loss, num_batches = eval_epoch(model, test_loader, log, savepath, e, 
                                                                                                                n_is_samples=config['n_is_samples'],
                                                                                                                plot_maxact=True, 
                                                                                                                plot_class_selectivity=True,
                                                                                                                wandb_on=config['wandb_on'])
            log("Val Avg Loss", total_loss / num_batches)
            log("Val Avg -LogP(x|z)", total_neg_logpx_z / num_batches)
            log("Val Avg KL", total_kl / num_batches)
            log("Val IS Estiamte", total_is_estimate / num_batches)
            log("Val EQ Loss", total_eq_loss / num_batches)


if __name__ == '__main__':
    main()