import sys
home_env = '../../../Reinforcement_Learning/'
sys.path.append(home_env)

from Resources import Networks as myNN
from Resources import MemoryMethods as myMM

import os
import time
import numpy as np
import numpy.random as rd
from collections import OrderedDict

import torch as T
import torch.nn as nn
import torch.optim as optim

class CriticNetwork(nn.Module):
    """ A simple and configurable multilayer perceptron.
        Actions are embedded into network after first layer.
    """
    def __init__(self, name, chpt_dir,
                       input_dims, n_actions,
                       depth, width, activ ):
        super(CriticNetwork, self).__init__()

        ## Defining the network features
        self.name       = name
        self.chpt_dir   = chpt_dir
        self.chpt_file  = os.path.join(self.chpt_dir, self.name)
        self.input_dims = input_dims
        self.n_actions  = n_actions

        ## Defining the state input layer which has a normalisation
        self.state_layer  = nn.Sequential(OrderedDict([
            ( "base_lin_1", nn.Linear(input_dims[0], width) ),
            ( "base_act_1", activ ),
            ( "base_nrm_1", nn.LayerNorm(width) ),
        ]))

        ## The actions are included from layer 2 onwards
        layers = []
        for l_num in range(2, depth+1):
            inpt = (n_actions+width) if l_num == 2 else width
            layers.append(( "comb_lin_{}".format(l_num), nn.Linear(inpt, width) ))
            layers.append(( "comb_act_{}".format(l_num), activ ))
        layers.append(( "comb_lin_out", nn.Linear(width, 1) ))
        self.comb_stream = nn.Sequential(OrderedDict(layers))

        ## The output layer gets special weight initialisation
        dev = 3e-3
        nn.init.uniform_(self.comb_stream.comb_lin_out.weight.data, -dev, dev )
        nn.init.uniform_(self.comb_stream.comb_lin_out.bias.data,   -dev, dev )

        ## Moving the network to the device
        self.device = T.device("cuda" if T.cuda.is_available() else "cpu")
        self.to(self.device)

    def forward(self, state, action):
        state_out = self.state_layer(state)
        combined = T.cat((state_out, action), 1 )
        q_value = self.comb_stream(combined)
        return q_value

    def save_checkpoint(self, flag=""):
        print("... saving critic network checkpoint ..." )
        T.save(self.state_dict(), self.chpt_file+flag)

    def load_checkpoint(self, flag=""):
        print("... loading critic network checkpoint ..." )
        self.load_state_dict(T.load(self.chpt_file+flag))

class ActorNetwork(nn.Module):
    """ A simple and configurable multilayer perceptron.
        Normalisation layer applied throughout.
        Tanh applied on final layer to clip the output.
        Scaling can then happen in post depending on env.
    """
    def __init__(self, name, chpt_dir,
                       input_dims, n_actions,
                       depth, width, activ,
                       noisy ):
        super(ActorNetwork, self).__init__()

        ## Defining the network features
        self.name       = name
        self.chpt_dir   = chpt_dir
        self.chpt_file  = os.path.join(self.chpt_dir, self.name)
        self.input_dims = input_dims
        self.n_actions  = n_actions

        # Checking if noisy layers will be used only on output
        if noisy:
            linear_layer = myNN.FactNoisyLinear
        else:
            linear_layer = nn.Linear

        layers = []
        for l_num in range(1, depth+1):
            inpt = input_dims[0] if l_num == 1 else width
            layers.append(( "lin_{}".format(l_num), linear_layer(inpt, width) ))
            layers.append(( "act_{}".format(l_num), activ ))
            layers.append(( "nrm_{}".format(l_num), nn.LayerNorm(width) ))
        layers.append(( "lin_out", linear_layer(width, n_actions) ))
        layers.append(( "act_out", nn.Tanh() ))
        self.main_stream = nn.Sequential(OrderedDict(layers))

        ## The output layer gets special weight initialisation
        dev = 3e-3
        nn.init.uniform_(self.main_stream.lin_out.weight.data, -dev, dev )
        nn.init.uniform_(self.main_stream.lin_out.bias.data,   -dev, dev )

        ## Moving the network to the device
        self.device = T.device("cuda" if T.cuda.is_available() else "cpu")
        self.to(self.device)

    def forward(self, state):
        action = self.main_stream(state)
        return action

    def save_checkpoint(self, flag=""):
        print("... saving actor network checkpoint ..." )
        T.save(self.state_dict(), self.chpt_file+flag)

    def load_checkpoint(self, flag=""):
        print("... loading actor network checkpoint ..." )
        self.load_state_dict(T.load(self.chpt_file+flag))


class Agent(object):
    def __init__(self,
                 name,
                 net_dir,
                 \
                 gamma,
                 input_dims, n_actions,
                 active, grad_clip, QL2,
                 noisy,
                 \
                 C_lr, C_depth, C_width,
                 A_lr, A_depth, A_width,
                 \
                 eps, eps_min, eps_dec,
                 \
                 delay, smooth_noise, noise_clip,
                 \
                 mem_size,    batch_size,
                 target_sync, freeze_up,
                 \
                 PER_on,      n_step,
                 PEReps,      PERa,
                 PERbeta,     PERb_inc,
                 PERmax,
                 ):

        ## Setting all class variables
        self.__dict__.update(locals())
        self.learn_step_counter = 0

        ## The twin critics and their corresponding target networks
        self.critic_1 = CriticNetwork( self.name + "_critic_1", net_dir,
                                       input_dims, n_actions,
                                       C_depth, C_width, active )
        self.critic_2 = CriticNetwork( self.name + "_critic_2", net_dir,
                                       input_dims, n_actions,
                                       C_depth, C_width, active )

        self.t_critic_1 = CriticNetwork( self.name + "_targ_critic_1", net_dir,
                                         input_dims, n_actions,
                                         C_depth, C_width, active )
        self.t_critic_2 = CriticNetwork( self.name + "_targ_critic_2", net_dir,
                                         input_dims, n_actions,
                                         C_depth, C_width, active )

        self.t_critic_1.load_state_dict( self.critic_1.state_dict() )
        self.t_critic_2.load_state_dict( self.critic_2.state_dict() )

        ## The actor and its corresponding target network
        self.actor = ActorNetwork( self.name + "_actor", net_dir,
                                   input_dims, n_actions,
                                   A_depth, A_width, active, noisy )
        self.t_actor = ActorNetwork( self.name + "_targ_actor", net_dir,
                                     input_dims, n_actions,
                                     A_depth, A_width, active, noisy )
        self.t_actor.load_state_dict( self.actor.state_dict() )

        ## The gradient descent algorithms and loss function
        self.C_optimiser_1 = optim.Adam( self.critic_1.parameters(), lr = C_lr, weight_decay = QL2 )
        self.C_optimiser_2 = optim.Adam( self.critic_2.parameters(), lr = C_lr, weight_decay = QL2 )
        self.A_optimiser = optim.Adam( self.actor.parameters(),  lr = A_lr )
        self.loss_fn = nn.SmoothL1Loss()

        ## Priotised experience replay for multi-timestep learning
        if PER_on and n_step > 1:
            self.memory = myMM.Cont_N_Step_PER( mem_size, input_dims, n_actions,
                                eps=PEReps, a=PERa, beta=PERbeta,
                                beta_inc=PERb_inc, max_priority=PERmax,
                                n_step=n_step, gamma=gamma )

        ## Standard experience replay
        elif not PER_on and n_step==1:
            self.memory = myMM.Cont_Exp_Replay( mem_size, input_dims, n_actions )

        else:
            print( "\n\n!!! Only options are n_step+per or none !!!\n\n" )
            exit()

    def save_models(self, flag=""):
        self.critic_1.save_checkpoint(flag)
        self.critic_2.save_checkpoint(flag)
        self.t_critic_1.save_checkpoint(flag)
        self.t_critic_2.save_checkpoint(flag)
        self.actor.save_checkpoint(flag)
        self.t_actor.save_checkpoint(flag)

    def load_models(self, flag=""):
        self.critic_1.load_checkpoint(flag)
        self.critic_2.load_checkpoint(flag)
        self.t_critic_1.load_checkpoint(flag)
        self.t_critic_2.load_checkpoint(flag)
        self.actor.load_checkpoint(flag)
        self.t_actor.load_checkpoint(flag)

    def store_transition(self, state, action, reward, next_state, done):
        self.memory.store_transition(state, action, reward, next_state, done)

    def sync_target_networks(self):

        if self.target_sync>1:
            print("\n\n\nWarning: DDPG only supports soft network updates\n\n\n")
            exit()

        for tp, pp in zip( self.t_critic_1.parameters(), self.critic_1.parameters() ):
            tp.data.copy_( self.target_sync * pp.data + ( 1.0 - self.target_sync ) * tp.data )

        for tp, pp in zip( self.t_critic_2.parameters(), self.critic_2.parameters() ):
            tp.data.copy_( self.target_sync * pp.data + ( 1.0 - self.target_sync ) * tp.data )

        for tp, pp in zip( self.t_actor.parameters(), self.actor.parameters() ):
            tp.data.copy_( self.target_sync * pp.data + ( 1.0 - self.target_sync ) * tp.data )

    def choose_action(self, state):

        ## Act completly randomly for the first x frames
        if self.memory.mem_cntr < self.freeze_up:
            action = np.random.uniform( -1, 1, self.n_actions )

        ## Then act purely greedily with noise
        else:
            with T.no_grad():
                state_tensor = T.tensor( state, device=self.actor.device, dtype=T.float32 )
                action = self.actor(state_tensor).cpu().numpy()

            ## If there are no noisy layers then we manually insert noise
            if not self.noisy:
                noise    = rd.uniform( -self.eps, self.eps, self.n_actions )
                self.eps = max( self.eps - self.eps_dec, self.eps_min )
                action   = np.clip( action + noise, -1, 1 )

        return action, 0

    def train(self):

        ## We dont train until the memory is at least one batch_size
        if self.memory.mem_cntr < max(self.batch_size, self.freeze_up):
            return 0

        ## Collect the batch
        states, actions, rewards, next_states, dones, is_weights, indices = self.memory.sample_memory(self.batch_size)

        ## We need to convert all of these arrays to pytorch tensors
        states      = T.tensor( states,      device = self.actor.device )
        actions     = T.tensor( actions,     device = self.actor.device )
        rewards     = T.tensor( rewards,     device = self.actor.device ).reshape(-1, 1)
        next_states = T.tensor( next_states, device = self.actor.device )
        dones       = T.tensor( dones,       device = self.actor.device ).reshape(-1, 1)
        is_weights  = T.tensor( is_weights,  device = self.actor.device )

        ## To increase the speed of this step we do it without keeping track of gradients
        with T.no_grad():

            ## First we need the optimising actions using the target actor
            next_actions = self.t_actor(next_states)

            ## We augment this with noise if noisy parameters arent already in use
            if not self.noisy:
                noise = T.normal( 0, std=self.smooth_noise, size=next_actions.shape, device=self.actor.device )
                noise = T.clamp( noise, -self.noise_clip, self.noise_clip )
                next_actions = T.clamp( next_actions+noise, -1, 1 )

            ## Now we find the values of those actions using both target critics and take the min
            next_Q_values_1 = self.t_critic_1( next_states, next_actions )
            next_Q_values_2 = self.t_critic_2( next_states, next_actions )
            next_Q_values = T.min(next_Q_values_1, next_Q_values_2)

            ## Now we can compute the TD targets
            td_target = rewards + ( self.gamma ** self.n_step ) * next_Q_values * (~dones)
            td_target = td_target.detach()

        ## We compute the current Q value estimates using the first critic
        Q_values_1 = self.critic_1(states, actions)

        ## Calculate the TD-Errors using Q1 to be used in PER and update the replay
        if self.PER_on:
            new_errors = T.abs(Q_values_1 - td_target).detach().cpu().numpy().squeeze()
            self.memory.batch_update(indices, new_errors)

        ## Update the Q-Function using gradient descent
        self.C_optimiser_1.zero_grad()
        C_loss_1 = self.loss_fn( Q_values_1, td_target )
        if self.PER_on:
            C_loss_1 = C_loss_1 * is_weights.unsqueeze(1)
        C_loss_1 = C_loss_1.mean()
        C_loss_1.backward()
        self.C_optimiser_1.step()

        ## We do the same steps for the second critic but we do not update PER
        self.C_optimiser_2.zero_grad()
        Q_values_2 = self.critic_2(states, actions)
        C_loss_2 = self.loss_fn( Q_values_2, td_target ).mean()
        C_loss_2.backward()
        self.C_optimiser_2.step()

        ## Only update policy and target networks every so often
        if self.learn_step_counter % self.delay == 0:

            ## Update the policy by one step of gradient ascent
            self.A_optimiser.zero_grad()
            best_actions = self.actor(states)
            A_loss = -self.critic_1(states, best_actions).mean()
            A_loss.backward()
            self.A_optimiser.step()

            ## Update the target network parameters
            self.sync_target_networks()

        self.learn_step_counter += 1

        return C_loss_1.item()+C_loss_2.item()
