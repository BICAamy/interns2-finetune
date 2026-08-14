# Configuration

`simulation.yaml` is the source of truth for the Step 5 E05-Pro continuous
entry-point environment. All public Cartesian values are millimetres in the
`robot_base` frame; the SOFA adapter alone converts them to metres.

The workspace box is only a coarse command filter. A point inside the box is
accepted only after the full six-axis inverse kinematics also finds a solution
at the configured safe TCP orientation and within all joint limits.

The current flange-to-needle transform `[0, 0, 150] mm / [0, 0, 0] deg` is a
simulation placeholder. Its `provisional: true` and
`real_robot_motion_allowed: false` flags must remain set until the installed
needle holder is measured and calibrated on the real robot.
