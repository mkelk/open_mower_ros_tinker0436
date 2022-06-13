#!/usr/bin/env python3

# ##################################################################
# Low-level control of Cherokey bot using rosserial
# ##################################################################

import math

import rospy
from std_msgs.msg import String
from std_msgs.msg import UInt16
from geometry_msgs.msg import Twist

# custom messages used by rosserial to communicate with Arduino on Cherokey
from cherokey_msgs.msg import WheelState
from cherokey_msgs.msg import Ticks

cherokey_pub = None

class Cherokey():
    '''Cherokey node that abstracts the Arduino-controlled motors

    Assumes node created and running already
    Creates listener on /cherokey/command to accept string-style commands.
    Creates listener on /cherokey/cmd_vel to accept twist messages sent specifically to Cherokey.
    Creates listener on /cherokey/speedspin to accept messages directly from OpenMower

    Attributes
    ----------
    speed : float
        Speed along the X axis in meters per second; positive is
        forward and negative is backward
    spin : float
        Rotation about the pivot point in radians per second; positive
        is clockwise when viewed from above (right spin)

    Methods
    -------
    stop()
        Stop all movement of the Cherokey

    '''
    def __init__(self, name,
                 wheel_diameter=0.068, wheel_base=0.136,
                 cal_distance=1.25, cal_duty=100, cal_time=5, skew=1.02,
                 pwm_freq=25):
        """
        Parameters
        ----------
        name: str
            The node name that will be used for this robot; defaults
            to "cherokey"
        wheel_diameter : float
            The diameter of the wheels in meters
        wheel_base : float
            The distance between the center of the wheels in meters
        cal_distance : float
            The distance travelled during a calibration time
            when running at 100% power
        cal_time : float
            Time elapsed in the calibration tst
        cal_duty : int
            Internal size of signal to motors in testing
        skew : float
            how much faster is left wheel than right, for correction, e.g. 1.02
        """
        self._signal_range = 255 
        max_rpm = cal_distance / (wheel_diameter * math.pi) / cal_time * 60 / cal_duty * self._signal_range
        self._left_max_rpm = max_rpm * (1+(skew-1)/2)
        self._right_max_rpm = max_rpm * (1-(skew-1)/2)
        rospy.loginfo(f"max rpm: {max_rpm}")
        rospy.loginfo(f"max rpm left: {self._left_max_rpm}")
        rospy.loginfo(f"max rpm right: {self._right_max_rpm}")
        self._wheel_diameter = wheel_diameter
        self._wheel_base = wheel_base
        self._pwm_freq = pwm_freq

        self.speed = 0.0
        self.spin = 0.0

        # create subscribers
        self._cmd_vel_subscription = rospy.Subscriber('/rover/cmd_vel', Twist, self._cmd_vel_callback)

        # set motor pwm freq
        # Note: TODO melk: we might want to make this a service to ensure that it is reveived
        # we might also want to wait to ensure that rosserial is running and sees the rover
        pub_freq.publish(self._pwm_freq)

        # just testing
        self._set_motor_speeds()

    def stop(self):
        self.speed = 0
        self.spin = 0
        self._set_motor_speeds()

    def max_twist(self):
        '''Rotation in radians per second at maximum RPM'''
        return self.max_speed() / self._wheel_diameter

    def _cmd_vel_callback(self, msg):
        rospy.logdebug(f"/rover/cmd_vel received: {msg}")
        self.speed = msg.linear.x
        # Note: Hand-adjusted calibration here...
        # very hard to turn the Cherokey
        self.spin = msg.angular.z 
        rospy.logdebug(f"spin set to: {self.spin}")
        rospy.logdebug(f"speed set to: {self.speed}")
        self._set_motor_speeds()

    def _set_motor_speeds(self):
        # TODO: inject a stop() if no speeds seen for a while
        #
        # max value that can be written to wheels, corresponding to the set max_rpm values
        # First figure out the speed of each wheel based on spin: each wheel
        # covers self._wheel_base meters in one radian, so the target speed
        # for each wheel in meters per sec is spin (radians/sec) times
        # wheel_base divided by wheel_diameter
        #
        right_twist_mps = self.spin * self._wheel_base / self._wheel_diameter
        left_twist_mps = -1.0 * self.spin * \
            self._wheel_base / self._wheel_diameter
        #
        # Now add in forward motion.
        #
        left_mps = self.speed + left_twist_mps
        right_mps = self.speed + right_twist_mps
        #
        # Convert meters/sec into RPM: for each revolution, a wheel travels
        # pi * diameter meters, and each minute has 60 seconds.
        #
        left_target_rpm = (left_mps * 60.0) / (math.pi * self._wheel_diameter)
        right_target_rpm = (right_mps * 60.0) / (math.pi * self._wheel_diameter)
        #
        left_percentage = (left_target_rpm / self._left_max_rpm) * 100.0
        right_percentage = (right_target_rpm / self._right_max_rpm) * 100.0
        #
        # clip to +- 100%
        left_percentage = max(min(left_percentage, 100.0), -100.0)
        right_percentage = max(min(right_percentage, 100.0), -100.0)
        #
        left_signal = (left_target_rpm / self._left_max_rpm) * self._signal_range
        right_signal = (right_target_rpm / self._right_max_rpm) * self._signal_range
        #
        left_dir = -1 if left_signal < 0 else 1
        right_dir = -1 if right_signal < 0 else 1
        left_signal_abs = left_signal * left_dir
        right_signal_abs = right_signal * right_dir

        # clip to signal max and deliver int
        signal_max =  max(left_signal_abs, right_signal_abs)
        if (signal_max > self._signal_range):
            left_signal_abs = left_signal_abs / signal_max * self._signal_range
            right_signal_abs = right_signal_abs / signal_max * self._signal_range
        left_signal_abs = int(min(left_signal_abs, self._signal_range))
        right_signal_abs = int(min(right_signal_abs, self._signal_range))
        #
        # rospy.loginfo(f"left_mps: {left_mps:.3f} right_mps: {right_mps:.3f}")
        # rospy.loginfo(f"left_target_rpm: {left_target_rpm:.3f} right_target_rpm: {right_target_rpm:.3f}")
        # rospy.loginfo(f"left_signal_abs: {left_signal_abs:.3f} right_signal_abs: {right_signal_abs:.3f}")

        pub_wheels.publish(left_signal_abs, left_dir, right_signal_abs, right_dir)        

def ticks_callback(ticks):
    pub_ticks.publish(ticks) 
    rospy.logdebug(f"Ticks left in Rover: {ticks.ticksLeft}")
    rospy.logdebug(f"Ticks right in Rover: {ticks.ticksRight}")

if __name__ == '__main__':
    rospy.loginfo("cherokey is starting")

    global pub_wheels
    global pub_freq
    global pub_ticks

    # start node
    node = rospy.init_node("cherokey")
    
    # start publisher for sending data over rosserial to Arduino on Rover
    pub_wheels = rospy.Publisher("/rover_ll/wheels_set_state", WheelState, queue_size=10)
    pub_freq = rospy.Publisher("/rover_ll/pwm_freq_set", UInt16, queue_size=10)

    # start subscriber to listen for ticks from low-level rover
    sub_ticks = rospy.Subscriber('/rover_ll/ticks', Ticks, ticks_callback, queue_size=10)

    # start publisher for sending Ticks on to OpenMower framework
    pub_ticks = rospy.Publisher("/rover/ticks", Ticks, queue_size=10)


    # start cherokey 
    cherokey = Cherokey('cherokey', cal_distance=1.1, cal_time=2, cal_duty=150, skew=0.7)
    rospy.loginfo("cherokey started")

    # # do some basic tests
    # cherokey.speed = 0.0 # in meters/sec
    # cherokey._set_motor_speeds()
    # rospy.sleep(2.0)

    # cherokey.speed = 0.0 # in meters/sec
    # cherokey._set_motor_speeds()
    # rospy.sleep(10.0)

    # rospy.loginfo("normal setting")
    # cherokey.speed = 0.25
    # cherokey.spin = 0.0
    # cherokey._set_motor_speeds()
    # rospy.sleep(4.0)

    # cherokey.speed = 0.0 # in meters/sec
    # cherokey._set_motor_speeds()
    # rospy.sleep(1.0)


    # rospy.loginfo("problem setting")
    # cherokey.speed = -0.5 
    # cherokey.spin = -0.16666666666666666 
    # cherokey._set_motor_speeds()
    # rospy.sleep(5)

    # rospy.loginfo("stop")
    # cherokey.speed = 0 # in meters/sec
    # cherokey.spin = 0.0
    # cherokey._set_motor_speeds()
    # rospy.sleep(1.0)


    rospy.spin()

    rospy.loginfo("cherokey is ending")

