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

## Step 3 real-mode configuration

`robot-real.example.yaml` is a deliberately incomplete, observe-only template.
Copy it to `configs/robot-real.local.yaml` on the deployment host, then fill in
only values that have actually been checked on site. The local file is ignored
by Git. Do not put passwords, private keys or gateway tokens in YAML.

From the new server's `app/` directory, validate without starting any service:

```bash
./scripts/services/start_all.sh --robot-mode real \
  --real-config configs/robot-real.local.yaml --check-config
```

The output reports a canonical SHA-256 and the number of missing motion-gating
fields. In Step 3, **even a complete configuration or `--real-control enabled`
cannot enable motion**: the provider is disconnected and observe-only. The
server and Mac will compare the canonical configuration digest during the later
gateway handshake; this command does not contact either device.
