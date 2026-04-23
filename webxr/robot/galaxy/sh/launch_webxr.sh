#!/bin/bash
/home/nvidia/can.bash

      
tmux new-session -d -s r1_lanuch \
    "cd /home/nvidia/test/install && source setup.bash && \
     roslaunch HDAS r1.launch" 

sleep 3

tmux new-session -d -s r1_chassis_control \
    "cd /home/nvidia/test/install && source setup.bash && \
     roslaunch mobiman r1_chassis_control.launch"


#!/bin/bash
tmux new-session -d -s mmp_jointTrackerdemo \
    "cd /home/nvidia/test/install && source setup.bash && \
     roslaunch mobiman mmp_jointTrackerdemo.launch" 

tmux new-session -d -s left_arm \
    "cd /home/nvidia/test/install && source setup.bash && \
     roslaunch mobiman SampleA_left_arm_relaxed_ik_mit.launch" 

tmux new-session -d -s right_arm \
    "cd /home/nvidia/test/install && source setup.bash && \
     roslaunch mobiman SampleA_right_arm_relaxed_ik_mit.launch"
