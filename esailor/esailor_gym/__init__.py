import logging

from gymnasium.envs.registration import register

logger = logging.getLogger(__name__)

#--------------------------------------------
#--> GAZEBO

#-> Eboat gymnasium_envs
register(
    id='EboatSingleWayPointEnvCC35-v0',
    entry_point='esailor_gym.envs:EboatSingleWayPointEnvCC35v0',
    max_episode_steps=1000000,
)

register(
    id='EboatSingleWayPointEnvCC25-v0',
    entry_point='esailor_gym.envs:EboatSingleWayPointEnvCC25v0',
    max_episode_steps=1000000,
)

register(
    id='EboatStraightLineEnvCC29-v0',
    entry_point='esailor_gym.envs:EboatStraightLineEnvCC29v0',
    max_episode_steps=1000000,
)

register(
    id='Eboat92_5-v0',
    entry_point='esailor_gym.envs:Eboat925_v0',
    max_episode_steps=1000000,
)

register(
    id='Eboat92-v0',
    entry_point='esailor_gym.envs:Eboat92_v0',
    max_episode_steps=1000000,
)

register(
    id='Eboat62-v0',
    entry_point='esailor_gym.envs:Eboat62_v0',
    max_episode_steps=1000000,
)


register(
    id='Eboat93-v0',
    entry_point='esailor_gym.envs:Eboat93_v0',
    max_episode_steps=1000000,
)


register(
    id='Eboat93-v1',
    entry_point='esailor_gym.envs:Eboat93_v1',
    max_episode_steps=1000000,
)

register(
    id='Eboat93-v2',
    entry_point='esailor_gym.envs:Eboat93_v2',
    max_episode_steps=1000000,
)

register(
    id='Eboat93-v3',
    entry_point='esailor_gym.envs:Eboat93_v3',
    max_episode_steps=1000000,
)