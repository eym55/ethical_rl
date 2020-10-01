import sys
from collections import deque
import numpy as np
import tensorflow as tf
from tensorflow import keras
from services.algorithms import AlgorithmBASE
from services.constants import *
from services.util import load_replay_buffer
from services.common.schedules.linear import Schedule as LinearSchedule

class DQNBASE(AlgorithmBASE):
  def __init__(self, **kwargs):
    super().__init__(**kwargs)

    self.replay_buffer = load_replay_buffer(kwargs[REPLAY_BUFFER_MODULE])(**kwargs)

    # This is a prioritized replay parameter. TODO: Make configurable
    # This value relects an "amount of prioritization" (starts small -> high).
    # The idea is that training instability in the beginning implies that importance sampling
    # is more important towards the end.
    self.replay_buffer_prioritization_start = float(kwargs[REPLAY_BUFFER_PRIORITIZATION_START])
    self.replay_buffer_prioritization_end = float(kwargs[REPLAY_BUFFER_PRIORITIZATION_END])
    self.beta_schedule = LinearSchedule(schedule_timesteps=self.number_of_episodes, final_p=self.replay_buffer_prioritization_end, initial_p=self.replay_buffer_prioritization_start) 
    self.replay_buffer_distribution_shape = float(kwargs[REPLAY_BUFFER_DISTRIBUTION_SHAPE])

    # This is how long we will wait before we start training the model - no reason to train until there's
    # enough data in the buffer.
    self.buffer_wait_steps = int(kwargs[BUFFER_WAIT_STEPS])

  def sample_experiences(self, episode_number):
    states, actions, rewards, next_states, dones, weights, buffer_indexes = self.replay_buffer.sample(self.batch_size, self.beta_schedule.value(episode_number))
    return states, actions, rewards, next_states, dones, weights, buffer_indexes

  def play_one_step(self, state, epsilon):
    action = self.policy.get_action(self.model, state, epsilon)
    next_state, reward, done, info = self.env.step(action)
    self.replay_buffer.add(state, action, reward, next_state, done)
    return next_state, reward, done, info

  def _update_model(self, states, actions, weights, target_Q_values):
    # TODO: Understand exactly what GradientTape does.
    mask = tf.one_hot(actions, self.n_outputs)
    with tf.GradientTape() as tape:
      all_Q_values = self.model(states)
      Q_values = tf.reduce_sum(all_Q_values * mask, axis=1, keepdims=True)
      # TODO: check that multiplication of weights here is correct.
      loss = tf.reduce_mean(weights * self.loss_function(target_Q_values, Q_values))
    grads = tape.gradient(loss, self.model.trainable_variables)
    self.optimizer.apply_gradients(zip(grads, self.model.trainable_variables))
    return Q_values

  def _update_replay_buffer(self, Q_values, target_Q_values, buffer_indexes):
    # this is TD error (i think)
    # TODO: really think about this so we're sure it is the correct calculation
    td_error = np.abs(np.subtract(Q_values.numpy().flatten(), target_Q_values))
    weighted_td_error = np.power(td_error, self.replay_buffer_distribution_shape)

    # update priority replay buffer
    self.replay_buffer.update_priorities(buffer_indexes, weighted_td_error)

  def _training_step(self, episode_number):
    states, actions, rewards, next_states, dones, weights, buffer_indexes = self.sample_experiences(episode_number)
    next_Q_values = self.model.predict(next_states)

    target_Q_values = self._get_target_q_values(next_Q_values, rewards, dones, next_states)
    Q_values = self._update_model(states, actions, weights, target_Q_values)
    self._update_replay_buffer(Q_values, target_Q_values, buffer_indexes)

  def _get_target_q_values(self, *args):
    raise NotImplementedError("Implemented By Child")