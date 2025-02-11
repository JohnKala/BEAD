import torch
import torch.nn as nn
from torch.autograd import Variable
from torch.utils.data import DataLoader
import torchvision.transforms as transforms
import torchvision.datasets
from sklearn.utils import shuffle
from sklearn.preprocessing import StandardScaler
from pickle import dump
import numpy as np
import h5py

from ..src.models import flows


##################  DEFINE MODEL  #####################
class ConvNet(nn.Module):
        def __init__(self, args):
            super(ConvNet, self).__init__()

            self.latent_dim = args.latent_dim
            self.test_mode = args.test_net

            if args.train_net:
                self.batch_size = args.batch_size
            if args.test_net:
                self.batch_size = args.test_batch_size
                
            self.q_z_output_dim = args.q_z_output_dim
            self.z_size = self.latent_dim
    
            self.q_z_nn = nn.Sequential(
                  nn.Conv2d(1, 32, kernel_size=(3,4), stride=(1), padding=(0)),
                  nn.BatchNorm2d(32),
                  nn.ReLU(),
                  nn.Conv2d(32, 16, kernel_size=(5,1), stride=(1), padding=(0)),
                  nn.BatchNorm2d(16),
                  nn.ReLU(),
                  nn.Conv2d(16, 8, kernel_size=(7,1), stride=(1), padding=(0)),
                  nn.BatchNorm2d(8),
                  nn.ReLU()
                  ) 
            #
            self.mult_bn1 = nn.BatchNorm1d(161) 
            self.dense1 = nn.Linear(161,self.q_z_output_dim) #161 - full(13+3)+met, 41-4LJ, 216 - full(13+4)+met+mult
            self.dnn_bn1 = nn.BatchNorm1d(self.q_z_output_dim)
            self.q_z_mean = nn.Linear(self.q_z_output_dim, self.latent_dim)
            self.q_z_logvar = nn.Linear(self.q_z_output_dim, self.latent_dim)
            #
            self.dense3 = nn.Linear(self.latent_dim, self.q_z_output_dim)
            self.dnn_bn3 = nn.BatchNorm1d(self.q_z_output_dim)
            self.dense4 = nn.Linear(self.q_z_output_dim, 161)
            self.dnn_bn4 = nn.BatchNorm1d(161)
            #
            self.p_x_nn = nn.Sequential(
                  nn.ConvTranspose2d(8, 16, kernel_size=(7,1), stride=(1), padding=(0)),
                  nn.BatchNorm2d(16),
                  nn.ReLU(),
                  nn.ConvTranspose2d(16, 32, kernel_size=(5,1), stride=(1), padding=(0)),
                  nn.BatchNorm2d(32),
                  nn.ReLU(),
                  nn.ConvTranspose2d(32, 1, kernel_size=(3,4), stride=(1), padding=(0))
                  ) 
            # log-det-jacobian = 0 without flows
            self.ldj = 0
    
        def encode(self, x, y):
          
            out = self.q_z_nn(x)
            # flatten
            out = out.view(out.size(0), -1)
            # concat met and mult then normalize
            out = torch.cat((out, y),axis=1)
            out = self.mult_bn1(out)
            # dense Layer 1
            out = self.dense1(out)
            out = self.dnn_bn1(out)
            out = torch.relu(out)
            # dense Layer 2
            mean  = self.q_z_mean(out)
            logvar = self.q_z_logvar(out)
            return mean, logvar
    
        def decode(self, z):
            # dense Layer 3
            out = self.dense3(z)
            out = self.dnn_bn3(out)
            out = torch.relu(out)
            # dense Layer 4
            out = self.dense4(out)
            out = self.dnn_bn4(out)
            out = torch.relu(out)
            # remove met and multiplicities (if mult -8)
            out = out[:,:-1]
            # reshape
            out = out.view(out.size(0), 8, 20, 1) #20-full(13+3), 5-4LJ, 26-full(13+4)
            # DeConv
            out = self.p_x_nn(out)
            
            return out
    
        def reparameterize(self, mean, logvar):
            z = mean + torch.randn_like(mean) * torch.exp(0.5 * logvar)
            return z
    
        def forward(self, x, y):
            mean, logvar = self.encode(x, y)
            z = self.reparameterize(mean, logvar)
            out = self.decode(z)
            return out, mean, logvar, self.ldj, z, z


class PlanarVAE(ConvNet):
    """
    Variational auto-encoder with planar flows in the decoder.
    """

    def __init__(self, args):
        super(PlanarVAE, self).__init__(args)

        # Initialize log-det-jacobian to zero
        self.log_det_j = 0

        # Flow parameters
        flow = flows.Planar
        self.num_flows = 6#args.num_flows

        # Amortized flow parameters
        self.amor_u = nn.Linear(self.q_z_output_dim, self.num_flows * self.z_size)
        self.amor_w = nn.Linear(self.q_z_output_dim, self.num_flows * self.z_size)
        self.amor_b = nn.Linear(self.q_z_output_dim, self.num_flows)

        # Normalizing flow layers
        for k in range(self.num_flows):
            flow_k = flow()
            self.add_module('flow_' + str(k), flow_k)

    def encode(self, x, y):

        batch_size = x.size(0)

        out = self.q_z_nn(x)
        # flatten
        out = out.view(out.size(0), -1)
        out = torch.cat((out, y),axis=1)
        # dense Layer 1
        out = self.dense1(out)
        out = self.dnn_bn1(out)
        out = torch.relu(out)
        # dense Layer 2
        mean  = self.q_z_mean(out)
        logvar = self.q_z_logvar(out)
      
        # return amortized u an w for all flows
        u = self.amor_u(out).view(batch_size, self.num_flows, self.z_size, 1)
        w = self.amor_w(out).view(batch_size, self.num_flows, 1, self.z_size)
        b = self.amor_b(out).view(batch_size, self.num_flows, 1, 1)

        return mean, logvar, u, w, b

    def forward(self, x, y):
        self.met = y
        self.log_det_j = 0

        z_mu, z_var, u, w, b = self.encode(x, y)

        # Sample z_0
        z = [self.reparameterize(z_mu, z_var)]

        # Normalizing flows
        for k in range(self.num_flows):
            flow_k = getattr(self, 'flow_' + str(k)) #planar.'flow_'+k
            z_k, log_det_jacobian = flow_k(z[k], u[:, k, :, :], w[:, k, :, :], b[:, k, :, :])
            z.append(z_k)
            self.log_det_j += log_det_jacobian

        x_decoded = self.decode(z[-1])

        return x_decoded, z_mu, z_var, self.log_det_j, z[0], z[-1]


class OrthogonalSylvesterVAE(ConvNet):
    """
    Variational auto-encoder with orthogonal flows in the decoder.
    """

    def __init__(self, args):
        super(OrthogonalSylvesterVAE, self).__init__(args)

        # Initialize log-det-jacobian to zero
        self.log_det_j = 0

        # Flow parameters
        flow = flows.Sylvester
        self.num_flows = 4#args.num_flows
        self.num_ortho_vecs = args.num_ortho_vecs

        assert (self.num_ortho_vecs <= self.z_size) and (self.num_ortho_vecs > 0)

        # Orthogonalization parameters
        if self.num_ortho_vecs == self.z_size:
            self.cond = 1.e-5
        else:
            self.cond = 1.e-6

        self.steps = 100
        identity = torch.eye(self.num_ortho_vecs, self.num_ortho_vecs)
        # Add batch dimension
        identity = identity.unsqueeze(0)
        # Put identity in buffer so that it will be moved to GPU if needed by any call of .cuda
        self.register_buffer('_eye', Variable(identity))
        self._eye.requires_grad = False

        # Masks needed for triangular R1 and R2.
        triu_mask = torch.triu(torch.ones(self.num_ortho_vecs, self.num_ortho_vecs), diagonal=1)
        triu_mask = triu_mask.unsqueeze(0).unsqueeze(3)
        diag_idx = torch.arange(0, self.num_ortho_vecs).long()

        self.register_buffer('triu_mask', Variable(triu_mask))
        self.triu_mask.requires_grad = False
        self.register_buffer('diag_idx', diag_idx)

        # Amortized flow parameters
        # Diagonal elements of R1 * R2 have to satisfy -1 < R1 * R2 for flow to be invertible
        self.diag_activation = nn.Tanh()

        self.amor_d = nn.Linear(self.q_z_output_dim, self.num_flows * self.num_ortho_vecs * self.num_ortho_vecs)

        self.amor_diag1 = nn.Sequential(
            nn.Linear(self.q_z_output_dim, self.num_flows * self.num_ortho_vecs),
            self.diag_activation
        )
        self.amor_diag2 = nn.Sequential(
            nn.Linear(self.q_z_output_dim, self.num_flows * self.num_ortho_vecs),
            self.diag_activation
        )

        self.amor_q = nn.Linear(self.q_z_output_dim, self.num_flows * self.z_size * self.num_ortho_vecs)
        self.amor_b = nn.Linear(self.q_z_output_dim, self.num_flows * self.num_ortho_vecs)

        # Normalizing flow layers
        for k in range(self.num_flows):
            flow_k = flow(self.num_ortho_vecs)
            self.add_module('flow_' + str(k), flow_k)

    def batch_construct_orthogonal(self, q):

        # Reshape to shape (num_flows * batch_size, z_size * num_ortho_vecs)
        q = q.view(-1, self.z_size * self.num_ortho_vecs)

        norm = torch.norm(q, p=2, dim=1, keepdim=True)
        amat = torch.div(q, norm)
        dim0 = amat.size(0)
        amat = amat.resize(dim0, self.z_size, self.num_ortho_vecs)

        max_norm = 0

        # Iterative orthogonalization
        for s in range(self.steps):
            tmp = torch.bmm(amat.transpose(2, 1), amat)
            tmp = self._eye - tmp
            tmp = self._eye + 0.5 * tmp
            amat = torch.bmm(amat, tmp)

            # Testing for convergence
            test = torch.bmm(amat.transpose(2, 1), amat) - self._eye
            norms2 = torch.sum(torch.norm(test, p=2, dim=2) ** 2, dim=1)
            norms = torch.sqrt(norms2)
            max_norm = torch.max(norms).data
            if max_norm <= self.cond:
                break

        if max_norm > self.cond:
            print('\nWARNING: orthogonalization not complete')
            print('\t Final max norm =', max_norm)

            # print()

        # Reshaping: first dimension is batch_size
        amat = amat.view(-1, self.num_flows, self.z_size, self.num_ortho_vecs)
        amat = amat.transpose(0, 1)

        return amat

    def encode(self, x, y):

        batch_size = x.size(0)

        out = self.q_z_nn(x)
        # flatten
        out = out.view(out.size(0), -1)
        out = torch.cat((out, y),axis=1)
        # dense Layer 1
        out = self.dense1(out)
        out = self.dnn_bn1(out)
        out = torch.relu(out)
        # dense Layer 2
        mean  = self.q_z_mean(out)
        logvar = self.q_z_logvar(out)

        # Amortized r1, r2, q, b for all flows

        full_d = self.amor_d(out)
        diag1 = self.amor_diag1(out)
        diag2 = self.amor_diag2(out)

        full_d = full_d.resize(batch_size, self.num_ortho_vecs, self.num_ortho_vecs, self.num_flows)
        diag1 = diag1.resize(batch_size, self.num_ortho_vecs, self.num_flows)
        diag2 = diag2.resize(batch_size, self.num_ortho_vecs, self.num_flows)

        r1 = full_d * self.triu_mask
        r2 = full_d.transpose(2, 1) * self.triu_mask

        r1[:, self.diag_idx, self.diag_idx, :] = diag1
        r2[:, self.diag_idx, self.diag_idx, :] = diag2

        q = self.amor_q(out)
        b = self.amor_b(out)

        # Resize flow parameters to divide over K flows
        b = b.resize(batch_size, 1, self.num_ortho_vecs, self.num_flows)

        return mean, logvar, r1, r2, q, b

    def forward(self, x, y):
        self.met = y
        self.log_det_j = 0

        z_mu, z_var, r1, r2, q, b = self.encode(x, y)

        # Orthogonalize all q matrices
        q_ortho = self.batch_construct_orthogonal(q)

        # Sample z_0
        z = [self.reparameterize(z_mu, z_var)]

        # Normalizing flows
        for k in range(self.num_flows):

            flow_k = getattr(self, 'flow_' + str(k))
            z_k, log_det_jacobian = flow_k(z[k], r1[:, :, :, k], r2[:, :, :, k], q_ortho[k, :, :, :], b[:, :, :, k])

            z.append(z_k)
            self.log_det_j += log_det_jacobian

        x_decoded = self.decode(z[-1])

        return x_decoded, z_mu, z_var, self.log_det_j, z[0], z[-1]


class HouseholderSylvesterVAE(ConvNet):
    """
    Variational auto-encoder with householder sylvester flows in the decoder.
    """

    def __init__(self, args):
        super(HouseholderSylvesterVAE, self).__init__(args)

        # Initialize log-det-jacobian to zero
        self.log_det_j = 0

        # Flow parameters
        flow = flows.Sylvester
        self.num_flows = 4#args.num_flows
        self.num_householder = args.num_householder
        assert self.num_householder > 0

        identity = torch.eye(self.z_size, self.z_size)
        # Add batch dimension
        identity = identity.unsqueeze(0)
        # Put identity in buffer so that it will be moved to GPU if needed by any call of .cuda
        self.register_buffer('_eye', Variable(identity))
        self._eye.requires_grad = False

        # Masks needed for triangular r1 and r2.
        triu_mask = torch.triu(torch.ones(self.z_size, self.z_size), diagonal=1)
        triu_mask = triu_mask.unsqueeze(0).unsqueeze(3)
        diag_idx = torch.arange(0, self.z_size).long()

        self.register_buffer('triu_mask', Variable(triu_mask))
        self.triu_mask.requires_grad = False
        self.register_buffer('diag_idx', diag_idx)

        # Amortized flow parameters
        # Diagonal elements of r1 * r2 have to satisfy -1 < r1 * r2 for flow to be invertible
        self.diag_activation = nn.Tanh()

        self.amor_d = nn.Linear(self.q_z_output_dim, self.num_flows * self.z_size * self.z_size)

        self.amor_diag1 = nn.Sequential(
            nn.Linear(self.q_z_output_dim, self.num_flows * self.z_size),
            self.diag_activation
        )
        self.amor_diag2 = nn.Sequential(
            nn.Linear(self.q_z_output_dim, self.num_flows * self.z_size),
            self.diag_activation
        )

        self.amor_q = nn.Linear(self.q_z_output_dim, self.num_flows * self.z_size * self.num_householder)

        self.amor_b = nn.Linear(self.q_z_output_dim, self.num_flows * self.z_size)

        # Normalizing flow layers
        for k in range(self.num_flows):
            flow_k = flow(self.z_size)

            self.add_module('flow_' + str(k), flow_k)

    def batch_construct_orthogonal(self, q):

        # Reshape to shape (num_flows * batch_size * num_householder, z_size)
        q = q.view(-1, self.z_size)

        norm = torch.norm(q, p=2, dim=1, keepdim=True)
        v = torch.div(q, norm)

        # Calculate Householder Matrices
        vvT = torch.bmm(v.unsqueeze(2), v.unsqueeze(1)) 

        amat = self._eye - 2 * vvT 

        # Reshaping: first dimension is batch_size * num_flows
        amat = amat.view(-1, self.num_householder, self.z_size, self.z_size)

        tmp = amat[:, 0]
        for k in range(1, self.num_householder):
            tmp = torch.bmm(amat[:, k], tmp)

        amat = tmp.view(-1, self.num_flows, self.z_size, self.z_size)
        amat = amat.transpose(0, 1)

        return amat

    def encode(self, x, y):

        batch_size = x.size(0)

        out = self.q_z_nn(x)
        # flatten
        out = out.view(out.size(0), -1)
        out = torch.cat((out, y),axis=1)
        # dense Layer 1
        out = self.dense1(out)
        out = self.dnn_bn1(out)
        out = torch.relu(out)
        # dense Layer 2
        mean  = self.q_z_mean(out)
        logvar = self.q_z_logvar(out)

        # Amortized r1, r2, q, b for all flows
        full_d = self.amor_d(out)
        diag1 = self.amor_diag1(out)
        diag2 = self.amor_diag2(out)

        full_d = full_d.resize(batch_size, self.z_size, self.z_size, self.num_flows)
        diag1 = diag1.resize(batch_size, self.z_size, self.num_flows)
        diag2 = diag2.resize(batch_size, self.z_size, self.num_flows)

        r1 = full_d * self.triu_mask
        r2 = full_d.transpose(2, 1) * self.triu_mask

        r1[:, self.diag_idx, self.diag_idx, :] = diag1
        r2[:, self.diag_idx, self.diag_idx, :] = diag2

        q = self.amor_q(out)
        b = self.amor_b(out)

        # Resize flow parameters to divide over K flows
        b = b.resize(batch_size, 1, self.z_size, self.num_flows)

        return mean, logvar, r1, r2, q, b

    def forward(self, x, y):
        self.met = y
        self.log_det_j = 0
        batch_size = x.size(0)

        z_mu, z_var, r1, r2, q, b = self.encode(x, y)

        # Orthogonalize all q matrices
        q_ortho = self.batch_construct_orthogonal(q)

        # Sample z_0
        z = [self.reparameterize(z_mu, z_var)]

        # Normalizing flows
        for k in range(self.num_flows):

            flow_k = getattr(self, 'flow_' + str(k))
            q_k = q_ortho[k]

            z_k, log_det_jacobian = flow_k(z[k], r1[:, :, :, k], r2[:, :, :, k], q_k, b[:, :, :, k], sum_ldj=True)

            z.append(z_k)
            self.log_det_j += log_det_jacobian

        x_decoded = self.decode(z[-1])

        return x_decoded, z_mu, z_var, self.log_det_j, z[0], z[-1]


class TriangularSylvesterVAE(ConvNet):
    """
    Variational auto-encoder with triangular sylvester flows in the decoder.
    """

    def __init__(self, args):
        super(TriangularSylvesterVAE, self).__init__(args)

        # Initialize log-det-jacobian to zero
        self.log_det_j = 0

        # Flow parameters
        flow = flows.TriangularSylvester
        self.num_flows = 4#args.num_flows

        # permuting indices corresponding to Q=P (permutation matrix) for every other flow
        flip_idx = torch.arange(self.z_size - 1, -1, -1).long()
        self.register_buffer('flip_idx', flip_idx)

        # Masks needed for triangular r1 and r2.
        triu_mask = torch.triu(torch.ones(self.z_size, self.z_size), diagonal=1)
        triu_mask = triu_mask.unsqueeze(0).unsqueeze(3)
        diag_idx = torch.arange(0, self.z_size).long()

        self.register_buffer('triu_mask', Variable(triu_mask))
        self.triu_mask.requires_grad = False
        self.register_buffer('diag_idx', diag_idx)

        # Amortized flow parameters
        # Diagonal elements of r1 * r2 have to satisfy -1 < r1 * r2 for flow to be invertible
        self.diag_activation = nn.Tanh()

        self.amor_d = nn.Linear(self.q_z_output_dim, self.num_flows * self.z_size * self.z_size)

        self.amor_diag1 = nn.Sequential(
            nn.Linear(self.q_z_output_dim, self.num_flows * self.z_size),
            self.diag_activation
        )
        self.amor_diag2 = nn.Sequential(
            nn.Linear(self.q_z_output_dim, self.num_flows * self.z_size),
            self.diag_activation
        )

        self.amor_b = nn.Linear(self.q_z_output_dim, self.num_flows * self.z_size)

        # Normalizing flow layers
        for k in range(self.num_flows):
            flow_k = flow(self.z_size)

            self.add_module('flow_' + str(k), flow_k)

    def encode(self, x, y):

        batch_size = x.size(0)

        out = self.q_z_nn(x)
        # flatten
        out = out.view(out.size(0), -1)
        out = torch.cat((out, y),axis=1)
        # dense Layer 1
        out = self.dense1(out)
        out = self.dnn_bn1(out)
        out = torch.relu(out)
        # dense Layer 2
        mean  = self.q_z_mean(out)
        logvar = self.q_z_logvar(out)

        # Amortized r1, r2, b for all flows
        full_d = self.amor_d(out)
        diag1 = self.amor_diag1(out)
        diag2 = self.amor_diag2(out)

        full_d = full_d.resize(batch_size, self.z_size, self.z_size, self.num_flows)
        diag1 = diag1.resize(batch_size, self.z_size, self.num_flows)
        diag2 = diag2.resize(batch_size, self.z_size, self.num_flows)

        r1 = full_d * self.triu_mask
        r2 = full_d.transpose(2, 1) * self.triu_mask

        r1[:, self.diag_idx, self.diag_idx, :] = diag1
        r2[:, self.diag_idx, self.diag_idx, :] = diag2

        b = self.amor_b(out)
          # Resize flow parameters to divide over K flows
        b = b.resize(batch_size, 1, self.z_size, self.num_flows)

        return mean, logvar, r1, r2, b

    def forward(self, x, y):
        self.met = y
        self.log_det_j = 0

        z_mu, z_var, r1, r2, b = self.encode(x, y)

        # Sample z_0
        z = [self.reparameterize(z_mu, z_var)]

        # Normalizing flows
        for k in range(self.num_flows):

            flow_k = getattr(self, 'flow_' + str(k))
            if k % 2 == 1:
                # Alternate with reorderering z for triangular flow
                permute_z = self.flip_idx
            else:
                permute_z = None

            z_k, log_det_jacobian = flow_k(z[k], r1[:, :, :, k], r2[:, :, :, k], b[:, :, :, k], permute_z, sum_ldj=True)

            z.append(z_k)
            self.log_det_j += log_det_jacobian

        x_decoded = self.decode(z[-1])

        return x_decoded, z_mu, z_var, self.log_det_j, z[0], z[-1]


class IAFVAE(ConvNet):
    """
    Variational auto-encoder with inverse autoregressive flows in the decoder.
    """

    def __init__(self, args):
        super(IAFVAE, self).__init__(args)

        # Initialize log-det-jacobian to zero
        self.log_det_j = 0
        self.h_size = args.made_h_size

        self.h_context = nn.Linear(self.q_z_output_dim, self.h_size)

        # Flow parameters
        self.num_flows = 4#args.num_flows # 4 for chan1
        self.flow = flows.IAF(z_size=self.z_size, num_flows=self.num_flows,
                              num_hidden=1, h_size=self.h_size, conv2d=False)

    def encode(self, x, y):
        
        out = self.q_z_nn(x)
        # flatten
        out = out.view(out.size(0), -1)
        out = torch.cat((out, y),axis=1)
        # dense Layer 1
        out = self.dense1(out)
        out = self.dnn_bn1(out)
        out = torch.relu(out)
        # dense Layer 2
        mean  = self.q_z_mean(out)
        logvar = self.q_z_logvar(out)

        # context from previous layer
        h_context = self.h_context(out)

        return mean, logvar, h_context

    def forward(self, x, y):
        self.met = y
        # mean and variance of z
        z_mu, z_var, h_context = self.encode(x, y)
        # sample z
        z_0 = self.reparameterize(z_mu, z_var)

        # iaf flows
        z_k, self.log_det_j = self.flow(z_0, h_context)

        # decode
        x_decoded = self.decode(z_k)

        return x_decoded, z_mu, z_var, self.log_det_j, z_0, z_k

class ConvFlowVAE(ConvNet):
    """
    Variational auto-encoder with convolutional flows in the decoder.
    """

    def __init__(self, args):
        super(ConvFlowVAE, self).__init__(args)

        # Initialize log-det-jacobian to zero
        self.log_det_j = 0
        self.num_flows = 4#args.num_flows # 6 for chan1
        self.kernel_size = args.convFlow_kernel_size

        flow_k = flows.CNN_Flow

        # Normalizing flow layers
        self.flow = flow_k(dim=self.latent_dim, cnn_layers=self.num_flows, kernel_size=self.kernel_size, test_mode=self.test_mode)

    def forward(self, x, y):
        self.met = y

        # mean and variance of z
        z_mu, z_var = self.encode(x, y)
        # sample z
        z_0 = self.reparameterize(z_mu, z_var)

        # Normalizing flows
        z_k, logdet = self.flow(z_0)

        x_decoded = self.decode(z_k)

        return x_decoded, z_mu, z_var, self.log_det_j, z_0, z_k

class NSF_AR_VAE(ConvNet):
    """
    Variational auto-encoder with auto-regressive neural spline flows in the decoder.
    """

    def __init__(self, args):
        super(NSF_AR_VAE, self).__init__(args)
        self.log_det_j = 0
        self.dim = args.latent_dim
        self.num_flows = 4 #args.num_flows

        flow = flows.NSF_AR

        # Normalizing flow layers
        for k in range(self.num_flows):
            flow_k = flow(dim=self.dim)

            self.add_module('flow_' + str(k), flow_k)

    def forward(self, x, y):
        self.met = y
        
        # mean and variance of z
        z_mu, z_var = self.encode(x, y)
        # sample z
        z = [self.reparameterize(z_mu, z_var)]

        for k in range(self.num_flows):

            flow_k = getattr(self, 'flow_' + str(k))

            z_k, log_det_jacobian = flow_k(z[k])

            z.append(z_k)
            self.log_det_j += log_det_jacobian

        x_decoded = self.decode(z[-1])

        return x_decoded, z_mu, z_var, self.log_det_j, z[0], z[-1]


