import sys
sys.path.append('/home/matthew/Documents/Reinforcement_Learning/')

import gym
import time
import numpy as np
import matplotlib.pyplot as plt
from itertools import count

import torch as T
import torch.nn as nn

from Environments import Car_Env
from Rainbow import Agent
from RLResources.Utils import score_plot
from RLResources.Utils import dist_plot

def main():

    test_mode = False
    load_checkpoint = False
    
    render_on = False
    draw_return = False
    interval = 10
    best_score = 2000
    
    env = Car_Env.MainEnv()
    # env = gym.make("CartPole-v1")
    # print( env.reset() )
    # print( env.action_space )
    # exit()
    
    agent = Agent( 
                    name    = "car_AI",
                    net_dir = "Saved_Binaries",
                    \
                    gamma = 0.99, lr = 1e-4,
                    \
                    input_dims = [28], n_actions = 12,
                    depth = 3, width = 128, 
                    activ = nn.PReLU(), noisy = True,
                    \
                    eps     = 1.0,
                    eps_min = 0.01,
                    eps_dec = 5e-5,
                    \
                    mem_size    = 500000, batch_size = 64,
                    target_sync = 1e-3,   freeze_up  = 10000,
                    \
                    PER_on    = True, n_step   = 3,
                    PEReps    = 0.01, PERa     = 0.5,
                    PERbeta   = 0.4,  PERb_inc = 1e-7,
                    PERmax_td = 3,
                    \
                    n_atoms = 51, sup_range = [-1, 25 ]
                    )
                    
    if load_checkpoint:
        agent.load_models()

    ## For plotting as it learns
    plt.ion()
    sp = score_plot("Rainbow")

    if draw_return:
        dp = dist_plot( agent.vmin, agent.vmax, agent.n_atoms)

    all_time = 0
    for ep in count():

        state = env.reset()
        ep_score = 0.0
        ep_loss  = 0.0
        ep_error = 0.0

        for t in count():
            if render_on:
                env.render()

            action, dist = agent.choose_action(state)
            next_state, reward, done, info = env.step(action)
            eps = agent.eps
            
            if not test_mode:
                agent.store_transition( state, action, reward, next_state, done )
                loss, error = agent.train()
                ep_loss  += loss
                ep_error += error

            state = next_state

            ep_score += reward
            all_time += 1.0
            
            print( "Score = {:.7}     \r".format( ep_score ), end="" )
            sys.stdout.flush()

            if draw_return and all_time%interval==0:
                dp.update(dist)

            if not test_mode:
                if all_time>=10000 and all_time%10000==0:
                    agent.save_models()
                if ep_score==2000:
                    agent.save_models("_best")

            if done: break

        ep_loss  /= (t+1)
        ep_error /= (t+1)

        print( "Episode {}: Reward = {:.7}, Loss = {:4.3f}, Error = {:4.3f}, Eps = {:4.3f}, Episode Time = {}, Total Time = {}".format( \
                                         ep, ep_score, ep_loss, ep_error, eps, t+1, all_time ) )

        sp.update(ep_score)


if __name__ == '__main__':
    main()
















