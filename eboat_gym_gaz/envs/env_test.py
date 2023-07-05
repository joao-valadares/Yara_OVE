import gym
import rospy
import roslaunch
import numpy as np
import os
import math
import time

from datetime import datetime

from gym import utils, spaces
from gym_gazebo.envs import gazebo_env
from std_srvs.srv import Empty

from std_msgs.msg import Float32, Int16, Float32MultiArray
from geometry_msgs.msg import Point
from gym.utils import seeding

from tf.transformations import quaternion_from_euler
from gazebo_msgs.srv import SetModelState
from gazebo_msgs.msg import ModelState

class GazeboOceanEboatEnvCC(gazebo_env.GazeboEnv):
    def __init__(self):
        self.EBOAT_HOME = "/home/lmdc/eboat_ws/src/eboat_gz_1"
        gazebo_env.GazeboEnv.__init__(self, os.path.join(self.EBOAT_HOME, "eboat_gazebo/launch/ocean.launch"))

        self.boomAng_pub   = rospy.Publisher("/eboat/control_interface/sail", Float32, queue_size=5)
        self.rudderAng_pub = rospy.Publisher("/eboat/control_interface/rudder", Float32, queue_size=5)
        self.propVel_pub   = rospy.Publisher("/eboat/control_interface/propulsion", Int16, queue_size=5)
        self.wind_pub      = rospy.Publisher("/eboat/atmosferic_control/wind", Point, queue_size=5)
        self.unpause       = rospy.ServiceProxy('/gazebo/unpause_physics', Empty)
        self.pause         = rospy.ServiceProxy('/gazebo/pause_physics', Empty)
        self.reset_proxy   = rospy.ServiceProxy('/gazebo/reset_simulation', Empty)
        self.set_state     = rospy.ServiceProxy('/gazebo/set_model_state', SetModelState)

        # --> GLOBAL VARIABLES
        self.DTOL  = 25.0  # --> Threshold for distance. If the boat goes far than INITIAL POSITION + DMAX, a done signal is trigged.
        self.D0    = None  # --> The intial distance from the waypoint
        self.DMAX  = None
        self.DPREV = None

        # --> We will use a rescaled action space
        self.action_space = spaces.Box(low=-1,
                                       high=1,
                                       shape=(3,),
                                       dtype=np.float32)

        # --> We will use a rescaled action space
        self.observation_space = spaces.Box(low=-1,
                                            high=1,
                                            shape=(5,),
                                            dtype=np.float32)
        self.reward_range = (-1, 1)

        self._seed()

        # --> SET WIND SPEED INITIAL VECTOR
        self.windSpeed = np.array([0.0, 9.0, 0.0], dtype=np.float32)

        # --> GET INITIAL DISTANCE FROM THE WAYPOINT
        while self.D0 is None:
            try:
                self.D0 = \
                rospy.wait_for_message("/eboat/mission_control/observations", Float32MultiArray, timeout=20).data[0]
                self.DMAX = self.D0 + self.DTOL  # --> IT TAKE THE INITIAL DISTANCE IN CONSIDERATION
                self.DPREV = self.D0
            except:
                pass

        # --> AUXILIARY VARS
        self.d2r = np.pi / 180.0
        self.count = 0
        self.step_count = 0

        # --> SUPPORT FOR RANDOM INITIALIZATION OF WIND SPEED AND DIRECTION
        np.random.seed(30)
        self.max_wind_speed  = 13
        wind_speed           = np.arange(0, self.max_wind_speed, dtype=np.float32)
        wind_direction       = np.arange(-180, 180, 10, dtype=int) * self.d2r
        boat_orientation     = np.arange(-180, 180, 20, dtype=int) * self.d2r
        wind_direction[0]   += 1  # -->it imposes the wind direction to start in -179
        boat_orientation[0] += 1  # -->it imposes the boat orientation to start in -179
        self.possible_initial_conditions = []
        for bo in boat_orientation:
            for ws in wind_speed:
                for wd in wind_direction:
                    self.possible_initial_conditions.append(np.array([bo, ws, wd], dtype=np.float32))
        self.possible_initial_conditions = np.array(self.possible_initial_conditions)

        # --> LOG FILE TO REGISTER INITIAL CONDITIONS (BOAT ORIENTATION, APPARENT WIND SPEED, APPARENT WIND ANGLE)
        sufix = "_" + datetime.now().strftime("%d%m%Y_%H_%M_%S")
        self.state_log_file = os.path.join(os.getcwd(), f"STATES_{sufix}.log")
        with open(self.state_log_file, "w") as f:
            f.write("bang,wspeed,wang\n")

    def rot(self, modulus, theta):
        R = np.array([[np.cos(theta), -np.sin(theta)],[np.sin(theta), np.cos(theta)]], dtype=np.float32)

        return np.dot(np.array([1, 0], dtype=np.float32) * modulus, R)

    def setWindSpeed(self, vector):
        self.windSpeed = vector

    def setMaxWindSpeed(self, value):
        self.max_wind_speed = value

    def getWindSpeed(self):
        return self.windSpeed

    def setState(self, model_name, pose, theta):
        state = ModelState()
        state.model_name = model_name
        state.reference_frame = "world"
        # pose
        state.pose.position.x = pose[0]
        state.pose.position.y = pose[1]
        state.pose.position.z = pose[2]
        quaternion = quaternion_from_euler(0, 0, theta)
        state.pose.orientation.x = quaternion[0]
        state.pose.orientation.y = quaternion[1]
        state.pose.orientation.z = quaternion[2]
        state.pose.orientation.w = quaternion[3]
        # twist
        state.twist.linear.x = 0
        state.twist.linear.y = 0
        state.twist.linear.z = 0
        state.twist.angular.x = 0
        state.twist.angular.y = 0
        state.twist.angular.z = 0

        rospy.wait_for_service('/gazebo/set_model_state')
        try:
            set_state = self.set_state
            result = set_state(state)
            assert result.success is True
        except rospy.ServiceException:
            print("/gazebo/get_model_state service call failed")

    def sampleInitialState(self, model_name):
        i = np.random.randint(low=0, high=self.possible_initial_conditions.shape[0])
        theta_boat, wind_speed, theta_wind = self.possible_initial_conditions[i, :]

        # -->Set the true wind vector
        self.windSpeed[:2] = self.rot(wind_speed, theta_wind)
        with open(self.state_log_file, "a") as f:
            f.write(f"{theta_boat}, {wind_speed}, {theta_wind}\n")

        # --> Set the boat's position and orientation
        self.setState(model_name, pose=np.zeros(shape=3, dtype=np.float32), theta=theta_boat)

    def getObservations(self):
        obsData = None
        while obsData is None:
            try:
                obsData = rospy.wait_for_message('/eboat/mission_control/observations', Float32MultiArray,
                                                 timeout=20).data
            except:
                pass
            # --> obsData = [distance, trajectory angle, linear velocity, aparent wind speed, aparent wind angle, boom angle, rudder angle, eletric propultion speed, roll angle]
            #               [   0    ,        1        ,       2        ,         3         ,         4         ,     5     ,      6      ,            7            ,     8     ]

        return np.array(obsData, dtype=float)

    def actionRescale(self, action):
        raction = np.zeros(3, dtype=np.float32)
        # --> Eletric propulsion [-5, 5]
        raction[0] = action[0] * 5.0
        # --> Boom angle [0, 90]
        raction[1] = (action[1] + 1) * 45.0
        # --> Rudder angle [-60, 60]
        raction[2] = action[2] * 60.0
        return raction

    def rescale(self, m, rmin, rmax, tmin, tmax):
        # rmin denote the minimum of the range of your measurement
        # rmax denote the maximum of the range of your measurement
        # tmin denote the minimum of the range of your desired target scaling
        # tmax denote the maximum of the range of your desired target scaling
        # m in [rmin,rmax] denote your measurement to be scaled
        # Then
        # m --> ((m−rmin)/(rmax−rmin))*(tmax-tmin)+tmin
        # will scale m linearly into [tmin,tmax] as desired.
        # To go step by step,
        # m --> m−rmin maps m to [0,rmax−rmin].
        # Next,
        # m --> (m−rmin)/(rmax−rmin)
        # maps m to the interval [0,1], with m=rmin mapped to 0 and m=rmax mapped to 1.
        # Multiplying this by (tmax−tmin) maps m to [0,tmax−tmin].
        # Finally, adding tmin shifts everything and maps m to [tmin,tmax] as desired.
        return (((m - rmin) / (rmax - rmin)) * (tmax - tmin) + tmin)

    def observationRescale(self, observations):
        lobs = len(observations)
        robs = np.zeros(lobs, dtype=np.float32)
        # --> Distance from the waypoint (m) [0   , DMAX];
        robs[0] = 2 * (observations[0] / self.DMAX) - 1
        # --> Trajectory angle               [-180, 180]
        robs[1] = observations[1] / 180.0
        # --> Boat linear velocity (m/s)     [0   , 10 ]
        robs[2] = observations[2] / 5 - 1
        # --> Aparent wind speed (m/s)       [0   , 30]
        robs[3] = observations[3] / 15 - 1
        # --> Apparent wind angle            [-180, 180]
        robs[4] = observations[4] / 180.0
        if lobs > 5:
            # --> Boom angle                     [0   , 90]
            robs[5] = (observations[5] / 45.0) - 1
            # --> Rudder angle                   [-60 , 60 ]
            robs[6] = observations[6] / 60.0
            # --> Electric propulsion speed      [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]
            robs[7] = observations[7] / 5.0
            # --> Roll angle                     [-180, 180]
            robs[8] = observations[8] / 180.0

        return robs

    def _seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def rewardFunction(self, obs):
        reward = (self.DPREV - obs[0]) / self.DMAX

        if reward > 0:
            reward *= (1.0 - 0.9 * abs(obs[7]) / 5.0)
        else:
            reward -= 0.01 * abs(obs[7])

        # --> obsData = [distance, trajectory angle, linear velocity, aparent wind speed, aparent wind angle, boom angle, rudder angle, eletric propultion speed, roll angle]
        #               [   0    ,        1        ,       2        ,         3         ,         4         ,     5     ,      6      ,            7            ,     8     ]

        return reward

    def step(self, action):
        # --> UNPAUSE SIMULATION
        rospy.wait_for_service("/gazebo/unpause_physics")
        try:
            self.unpause()
        except(rospy.ServiceException) as e:
            print(("/gazebo/unpause_physics service call failed!"))

        # -->SEND ACTION TO THE BOAT CONTROL INTERFACE
        ract = self.actionRescale(action)
        self.propVel_pub.publish(int(ract[0]))
        self.boomAng_pub.publish(ract[1])
        self.rudderAng_pub.publish(ract[2])

        # -->GET OBSERVATIONS (NEXT STATE)
        observations = self.getObservations()

        # -->PAUSE SIMULATION
        rospy.wait_for_service("/gazebo/pause_physics")
        try:
            self.pause()
        except(rospy.ServiceException) as e:
            print(("/gazebo/pause_physics service call failed!"))

        # -->CALCULATES THE REWARD
        reward = self.rewardFunction(observations)

        # -->UPDATE PREVIOUS STATE VARIABLES
        self.DPREV = observations[0]

        # -->CHECK FOR A TERMINAL STATE
        done = bool((self.DPREV <= 5) |
                    (self.DPREV > self.DMAX) |
                    (np.isnan(observations).any())
                    )

        if np.isnan(observations).any():
            print("\n\n-------------------------------------")
            print(f"distance: {observations[0]}")
            print(f"traj ang: {observations[1]}")
            print(f"boat vel: {observations[2]}")
            print(f"wind vel: {observations[3]}")
            print(f"wind ang: {observations[4]}")
            print(f"boom ang: {observations[5]}")
            print(f"rud ang : {observations[6]}")
            print(f"prop    : {observations[7]}")
            print(f"roll ang: {observations[8]}")
            print("-------------------------------------\n")
            # --> WAIT FOR ACKNOWLEDGEMENT FROM USER
            # _ = input("Unpause: ")

        # -->PROCESS DONE SIGNAL
        if done:
            if (self.DPREV <= 5):
                reward = 1
            else:
                reward = -1

        self.step_count += 1

        return self.observationRescale(observations[:5]), reward, done, {}

    def reset(self):
        # -->RESETS THE STATE OF THE ENVIRONMENT.
        rospy.wait_for_service('/gazebo/reset_simulation')
        try:
            self.reset_proxy()
        except (rospy.ServiceException) as e:
            print(("/gazebo/reset_simulation service call failed!"))

        # -->UNPAUSE SIMULATION TO MAKE OBSERVATION
        rospy.wait_for_service('/gazebo/unpause_physics')
        try:
            self.unpause()
        except(rospy.ServiceException) as e:
            print(("/gazebo/unpause_physics service call failed!"))

        # -->SET THE ACTUATORS BACK TO THE DEFAULT SETTING
        self.propVel_pub.publish(0)
        self.boomAng_pub.publish(0.0)
        self.rudderAng_pub.publish(0.0)

        # -->SET RANDOM INITIAL STATE
        self.sampleInitialState("eboat")
        self.wind_pub.publish(Point(self.windSpeed[0], self.windSpeed[1], self.windSpeed[2]))

        # -->COLLECT OBSERVATIONS
        observations = self.getObservations()

        # -->RESET INITIAL STATE VALUES
        self.DPREV = observations[0]

        # -->PAUSE SIMULATION
        rospy.wait_for_service("/gazebo/pause_physics")
        try:
            self.pause()
        except(rospy.ServiceException) as e:
            print(("/gazebo/pause_physics service call failed!"))

        self.count += 1

        return self.observationRescale(observations[:5])


class GazeboOceanEboatEnvCC1(GazeboOceanEboatEnvCC):
    def __init__(self):
        self.EBOAT_HOME = "/home/lmdc/eboat_ws/src/eboat_gz_1"
        gazebo_env.GazeboEnv.__init__(self, os.path.join(self.EBOAT_HOME, "eboat_gazebo/launch/ocean.launch"))

        self.boomAng_pub   = rospy.Publisher("/eboat/control_interface/sail", Float32, queue_size=5)
        self.rudderAng_pub = rospy.Publisher("/eboat/control_interface/rudder", Float32, queue_size=5)
        self.propVel_pub   = rospy.Publisher("/eboat/control_interface/propulsion", Int16, queue_size=5)
        self.wind_pub      = rospy.Publisher("/eboat/atmosferic_control/wind", Point, queue_size=5)
        self.unpause       = rospy.ServiceProxy('/gazebo/unpause_physics', Empty)
        self.pause         = rospy.ServiceProxy('/gazebo/pause_physics', Empty)
        self.reset_proxy   = rospy.ServiceProxy('/gazebo/reset_simulation', Empty)
        self.set_state     = rospy.ServiceProxy('/gazebo/set_model_state', SetModelState)

        # --> GLOBAL VARIABLES
        self.DTOL   = 25.0  # --> Threshold for distance. If the boat goes far than INITIAL POSITION + DMAX, a done signal is trigged.
        self.D0     = None  # --> The intial distance from the waypoint
        self.DMAX   = None
        self.DPREV  = None  #--> DISTANCE IN PREVIOUS STATE
        self.RAPREV = None  #--> RUDDER ANGLE IN PREVIOUS STATE
        self.BAPREV = None  #--> BOOM ANGLE IN PREVIOUS STATE
        self.PEN    = -1.0 / 75.0

        # --> We will use a rescaled action space
        self.action_space = spaces.Box(low=-1,
                                       high=1,
                                       shape=(3,),
                                       dtype=np.float32)

        # --> We will use a rescaled action space
        self.observation_space = spaces.Box(low=-1,
                                            high=1,
                                            shape=(9,),
                                            dtype=np.float32)
        self.reward_range = (-1, 1)

        self._seed()

        # --> SET WIND SPEED INITIAL VECTOR
        self.windSpeed = np.array([0.0, 9.0, 0.0], dtype=np.float32)

        # --> GET INITIAL DISTANCE FROM THE WAYPOINT
        while self.D0 is None:
            try:
                self.D0    = rospy.wait_for_message("/eboat/mission_control/observations", Float32MultiArray, timeout=20).data[0]
                self.DMAX  = self.D0 + self.DTOL  # --> IT TAKE THE INITIAL DISTANCE IN CONSIDERATION
                self.DPREV = self.D0
            except:
                pass

        # --> AUXILIARY VARS
        self.d2r = np.pi / 180.0
        self.count = 0
        self.step_count = 0

        # --> SUPPORT FOR RANDOM INITIALIZATION OF WIND SPEED AND DIRECTION
        np.random.seed(30)
        self.max_wind_speed  = 13
        wind_speed           = np.arange(0, self.max_wind_speed, dtype=np.float32)
        wind_direction       = np.arange(-180, 181,  5, dtype=int) * self.d2r
        boat_orientation     = np.arange(-180, 181, 15, dtype=int) * self.d2r
        wind_direction[0]   += 1                                          #-->it imposes the wind direction to start in -179
        boat_orientation[0] += 1                                          #-->it imposes the boat orientation to start in -179
        self.possible_initial_conditions = []
        for bo in boat_orientation:
            for ws in wind_speed:
                for wd in wind_direction:
                    self.possible_initial_conditions.append([bo, ws, wd])
        self.possible_initial_conditions = np.array(self.possible_initial_conditions)

        #--> LOG FILE TO REGISTER INITIAL CONDITIONS (BOAT ORIENTATION, APPARENT WIND SPEED, APPARENT WIND ANGLE)
        sufix = "_" + datetime.now().strftime("%d%m%Y_%H_%M_%S")
        self.state_log_file = os.path.join(os.getcwd(),f"STATES_{sufix}.log")
        with open(self.state_log_file, "w") as f:
            f.write("bang,wspeed,wang\n")

    def rewardFunctionV0(self, obs):
        dRA = abs(self.RAPREV - obs[6])
        dBA = abs(self.BAPREV - obs[5])
        wa  = abs(obs[4])
        ps  = abs(obs[7])

        reward = (self.DPREV - obs[0]) / self.DMAX

        if reward > 0:
            if obs[1] < 60:
                reward *= 1.2

            if wa > 155:
                reward *= 0.4
            elif wa < 45:
                reward -= 1.05 * reward

        if reward > 0:
            reward *= (1.0 - 0.9 * ps / 5.0)
        else:
            reward -= 0.01 * ps

        # reward -= 0.001 * (dBA + dRA + ps)

        # --> obsData = [distance, trajectory angle, linear velocity, aparent wind speed, aparent wind angle, boom angle, rudder angle, eletric propultion speed, roll angle]
        #               [   0    ,        1        ,       2        ,         3         ,         4         ,     5     ,      6      ,            7            ,     8     ]

        return reward

    def rewardFunctionV1(self, obs):
        wa = abs(obs[4])
        ps = abs(obs[7])

        reward = self.PEN

        if (obs[1] < 60):
            reward -= 0.2 * self.PEN

        if (wa > 29):
            reward -= 0.1 * self.PEN

        if (wa < 136):
            reward -= 0.2 * self.PEN

        if (ps < 1):
            reward -= 0.4 * self.PEN

        # if ((obs[1] < 60) & (ps < 1) & (wa > 29) & (wa < 136)):
        #     reward *= 0.5

        return reward

    def rewardFunction(self, obs):
        dS  = (self.DPREV - obs[0]) / self.DMAX
        dRA = abs(self.RAPREV - obs[6])
        dBA = abs(self.BAPREV - obs[5])
        wa  = abs(obs[4])
        ps  = abs(obs[7])
        ba  = abs(obs[5])

        rwd = dS

        if rwd > 0:
            if obs[1] < 60:
                rwd += 0.2 * dS

            if (wa > 29) & (wa < 136) & (obs[2] > 0):
                rwd += 0.05 * obs[2]

        if rwd > 0:
            rwd *= (1.0 - 0.9 * ps / 5.0)
            if ba < 5:
                rwd *= 0.7
        else:
            rwd -= 0.01 * ps

        # rwd -= 0.001 * (dBA + dRA + ps)

        # --> obsData = [distance, trajectory angle, surge velocity, aparent wind speed, aparent wind angle, boom angle, rudder angle, eletric propultion speed, roll angle]
        #               [   0    ,        1        ,       2        ,         3         ,         4         ,     5     ,      6      ,            7            ,     8     ]

        return rwd

    def step(self, action):
        #--> UNPAUSE SIMULATION
        rospy.wait_for_service("/gazebo/unpause_physics")
        try:
            self.unpause()
        except( rospy.ServiceException) as e:
            print(("/gazebo/unpause_physics service call failed!"))

        #-->SEND ACTION TO THE BOAT CONTROL INTERFACE
        ract = self.actionRescale(action)
        self.propVel_pub.publish(int(ract[0]))
        self.boomAng_pub.publish(ract[1])
        self.rudderAng_pub.publish(ract[2])

        #-->GET OBSERVATIONS (NEXT STATE)
        observations = self.getObservations()

        #-->PAUSE SIMULATION
        rospy.wait_for_service("/gazebo/pause_physics")
        try:
            self.pause()
        except( rospy.ServiceException) as e:
            print(("/gazebo/pause_physics service call failed!"))

        #-->CALCULATES THE REWARD
        reward = self.rewardFunction(observations)

        # -->UPDATE PREVIOUS STATE VARIABLES
        self.DPREV  = observations[0]
        self.BAPREV = observations[5]
        self.RAPREV = observations[6]
        self.step_count += 1

        #-->CHECK FOR A TERMINAL STATE
        done = bool((self.DPREV <= 5) |
                    (self.DPREV > self.DMAX) |
                    (np.isnan(observations).any()) |
                    (self.count > 75)
                    )

        if np.isnan(observations).any():
            print("\n\n-------------------------------------")
            print(f"distance: {observations[0]}")
            print(f"traj ang: {observations[1]}")
            print(f"boat vel: {observations[2]}")
            print(f"wind vel: {observations[3]}")
            print(f"wind ang: {observations[4]}")
            print(f"boom ang: {observations[5]}")
            print(f"rud ang : {observations[6]}")
            print(f"prop    : {observations[7]}")
            print(f"roll ang: {observations[8]}")
            print("-------------------------------------\n")
            #--> WAIT FOR ACKNOWLEDGEMENT FROM USER
            # _ = input("Unpause: ")

        #-->PROCESS DONE SIGNAL
        if done:
            if (self.DPREV <= 5):
                reward = 1
            elif ((self.DPREV > self.DMAX) | (self.count > 75)):
                reward = -1
            else:
                pass

        self.step_count += 1

        return self.observationRescale(observations), reward, done, {}

    def reset(self):
        #-->RESETS THE STATE OF THE ENVIRONMENT.
        rospy.wait_for_service('/gazebo/reset_simulation')
        try:
            self.reset_proxy()
        except (rospy.ServiceException) as e:
            print(("/gazebo/reset_simulation service call failed!"))

        #-->UNPAUSE SIMULATION TO MAKE OBSERVATION
        rospy.wait_for_service('/gazebo/unpause_physics')
        try:
            self.unpause()
        except( rospy.ServiceException) as e:
            print(("/gazebo/unpause_physics service call failed!"))

        #-->SET THE ACTUATORS BACK TO THE DEFAULT SETTING
        self.propVel_pub.publish(0)
        self.boomAng_pub.publish(0.0)
        self.rudderAng_pub.publish(0.0)

        #-->SET RANDOM INITIAL STATE
        self.sampleInitialState("eboat")
        self.wind_pub.publish(Point(self.windSpeed[0], self.windSpeed[1], self.windSpeed[2]))

        #-->COLLECT OBSERVATIONS
        observations = self.getObservations()

        #-->RESET INITIAL STATE VALUES
        self.DPREV  = observations[0]
        self.BAPREV = observations[5]
        self.RAPREV = observations[6]
        self.count  = 0

        #-->PAUSE SIMULATION
        rospy.wait_for_service("/gazebo/pause_physics")
        try:
            self.pause()
        except( rospy.ServiceException) as e:
            print(("/gazebo/pause_physics service call failed!"))

        self.count += 1

        return self.observationRescale(observations)