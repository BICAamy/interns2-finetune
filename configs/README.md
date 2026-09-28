# Configuration

`simulation.yaml` is the source of truth for the Step 5 E05-Pro continuous
entry-point environment. All public Cartesian values are millimetres in the
`robot_base` frame; the SOFA adapter alone converts them to metres.

The workspace box is only a coarse command filter. A point inside the box is
accepted only after the full six-axis inverse kinematics also finds a solution
at the configured safe TCP orientation and within all joint limits.

The `[0, 0, 150] mm` flange-to-needle transform belongs only to simulation.
Keep its `provisional: true` and `real_robot_motion_allowed: false` flags; do
not copy it into a real-robot configuration. For bare-flange bench work,
the separate real configuration may use `tool.setup: flange_only_no_tool`
only after confirming that no attachment is installed and the controller's
selected/named TCP, Base UCS, payload, center of gravity, and both base
installing angles agree with the recorded values. The flange center is then
the temporary calculation point, not a physical needle tip. Installing any
attachment invalidates this profile and requires a new calibration.

## Step 3 real-mode configuration

`robot-real.example.yaml` is a deliberately incomplete, observe-only template.
`robot-real.local.yaml` is the checked-in configuration for the project's only
real robot. Update it only with values checked on site and commit the change so
the Mac and server can use the same Git revision. Do not put passwords, private
keys or gateway tokens in YAML; `configs/gateway-auth.local` remains ignored.

From the new server's `app/` directory, validate without starting any service:

```bash
./scripts/services/start_all.sh --robot-mode real \
  --real-config configs/robot-real.local.yaml --check-config
```

The output reports the selected control mode and number of missing motion-gating
fields. In Step 3, **even a complete configuration or `--real-control enabled`
cannot enable motion**: the provider is disconnected and observe-only. The
server and Mac obtain this configuration through Git; runtime commands no longer
accept or compare a separately copied checksum. This command does
not contact either device.

The no-tool profile validates zero flange-to-TCP translation/rotation, zero
payload/center of gravity, a confirmed TCP name, and the two measured base
installing angles. `--check-config` only validates data: it cannot prove the
flange is physically bare or that Gate C has passed. With this profile, the
read-only probe compares controller readbacks before a real gateway can start.
It does not enable a motion command path; Step 11 commissioning remains separate.
