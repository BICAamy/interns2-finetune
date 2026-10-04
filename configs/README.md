# Configuration

`simulation.yaml` is the source of truth for the Step 5 E05-Pro continuous
entry-point environment. All public Cartesian values are millimetres in the
`robot_base` frame; the SOFA adapter alone converts them to metres.

The workspace box is only a coarse command filter. A point inside the box is
accepted only after the full six-axis inverse kinematics also finds a solution
at the configured safe TCP orientation and within all joint limits.

The simulation and real-robot YAML files currently use the same command speed,
maximum speed, maximum relative distance, Cartesian workspace, position
tolerance, and joint limits. They remain separate sources of truth: simulation
loads only `simulation.yaml`, while real mode loads only
`robot-real.local.yaml`. Updating one file never changes the other mode
implicitly.

The current simulation and real configurations both use zero flange-to-TCP
translation and rotation because no tool is installed. The flange center is
therefore the temporary calculation point. The simulation transform remains
`provisional: true` and cannot authorize real motion. Installing any attachment
invalidates the zero-offset assumption and requires a new TCP calibration.

## Real-mode configuration

`robot-real.example.yaml` is a deliberately incomplete template.
`robot-real.local.yaml` is the checked-in configuration for the project's only
real robot. Update it only with values checked on site and commit the change so
the Mac and server can use the same Git revision. Do not put passwords, private
keys or gateway tokens in YAML; `configs/gateway-auth.local` remains ignored.

From the new server's `app/` directory, validate without starting any service:

```bash
./scripts/services/start_all.sh --robot-mode real \
  --real-config configs/robot-real.local.yaml --check-config
```

The output reports the number of missing motion-gating fields. There is no
startup control mode: the real runtime always waits for the authenticated Mac
gateway, and the physical enabled state comes only from controller feedback.
The server and Mac obtain this configuration through Git; runtime commands no
longer accept or compare a separately copied checksum. This command does not
contact either device.

For a normal real-mode launch, `start_all.sh` also reads
`motion.speed_mm_s` and `limits.max_speed_mm_s` from this YAML and exports them
to agent-web. Therefore the speed shown in the web proposal, included in its
fingerprint, checked by robot-runtime, and finally encoded by the Mac all comes
from the same checked-in configuration. Real mode does not use the simulation
defaults from `.env` for these two values.

The no-tool profile validates zero flange-to-TCP translation/rotation, zero
payload/center of gravity, a confirmed TCP name, and the two measured base
installing angles. `--check-config` only validates data: it cannot prove the
flange is physically bare or that Gate C has passed. The probe compares
controller readbacks before a real gateway can start. Enable/disable and the
approved single-axis relative motion are dispatched only through the
authenticated gateway; motion additionally requires one matching web
fingerprint confirmation.
