import traceback

# get PPO to run for L2R
import tensorflow as tf
import numpy as np
from canton import *
import gym

import threading as th
import math, time

from ppo import MultiCategoricalContinuous
from ppo2 import ppo_agent2, SingleEnvSampler, flatten
from farmer import farmer as farmer_class

# instead of repeatedly using one environment instance, obtain a new one everytime current environment is done.
class DisposingSampler(SingleEnvSampler):
    def get_env(self): # obtain a new environment on demand
        global farmer
        while 1:
            remote_env = farmer.acq_env()
            if remote_env == False: # no free environment
                time.sleep(0.1)
            else:
                if hasattr(self, 'remote_env'):
                    del self.remote_env # release previous before allocate new

                self.remote_env = remote_env
                from multi import fastenv
                fenv = fastenv(remote_env,2)
                # a skip of 2; also performs observation processing
                return fenv

    def __init__(self, agent, writer):
        super().__init__(env=None, agent=agent, writer = writer)

# policy for L2R.
class AwesomePolicy(Can):
    def __init__(self, ob_space, ac_space):
        super().__init__()

        # 1. assume probability distribution is continuous
        assert len(ac_space.shape) == 1
        self.ac_dims = ac_dims = ac_space.shape[0]
        self.ob_dims = ob_dims = ob_space.shape[0]

        # 2. build our action network
        rect = Act('tanh')
        # apparently John doesn't give a fuck about ReLUs. Change the rectifiers as you wish.
        rect = Act('lrelu',alpha=0.2)
        magic = 1/(0.5+0.5*0.2) # stddev factor for lrelu(0.2)

        c = Can()
        c.add(Dense(ob_dims, 800, stddev=magic))
        c.add(rect)
        c.add(Dense(800, 400, stddev=magic))
        c.add(rect)
        c.add(Dense(400, ac_dims*3, stddev=1))
        # self.dist = c.add(Bernoulli())
        self.dist = c.add(MultiCategoricalContinuous(ac_dims, 3))
        c.chain()
        self.actor = self.add(c)

        # 3. build our value network
        c = Can()
        c.add(Dense(ob_dims, 800, stddev=magic))
        c.add(rect)
        c.add(Dense(800, 400, stddev=magic))
        c.add(rect)
        c.add(Dense(400, 1, stddev=1))
        c.chain()
        self.critic = self.add(c)


if __name__ == '__main__':
    farmer = farmer_class()

    from osim.env import RunEnv
    runenv = RunEnv(visualize=False)
    from gym.spaces import Box

    from observation_processor import processed_dims
    ob_space = Box(-1.0, 1.0, (processed_dims,))

    agent = ppo_agent2(
        ob_space, runenv.action_space,
        horizon=2048, # minimum steps to collect before policy update
        gamma=0.99, # discount factor for reward
        lam=0.95, # smooth factor for advantage estimation
        train_epochs=10, # how many epoch over data for one update
        batch_size=128, # batch size for training
        buffer_length=16,

        policy=AwesomePolicy
    )

    get_session().run(gvi()) # init global variables for TF

    # parallelized
    process_count = 1 # total horizon = process_count * agent.horizon
    tf_writer = tf.summary.FileWriter('tensorboard')
    samplers = [DisposingSampler(agent, tf_writer) for i in range(process_count)]

    iterations = 10000

    for T in range(iterations):
        print('start running')
        agent.iterate_once_on_samplers(samplers)
        print('optimization iteration {}/[]'.format(T, iterations))
        if np.mod(T, 100) == 0 and T >= 100:
            agent.current_policy.save_weights('ppo_pol.npz')
            agent.old_policy.save_weights('ppo_old.npz')
        print("Finish.")

    def save():
        agent.current_policy.save_weights('ppo_pol.npz')
        agent.old_policy.save_weights('ppo_old.npz')

    def load():
        agent.current_policy.load_weights('ppo_pol.npz')
        agent.old_policy.load_weights('ppo_old.npz')