#!/usr/bin/env bash
set -euo pipefail

# IRIS sessions can exit successfully after an ObjectScript error. Require a
# fresh success marker before allowing this startup hook to complete.
rm -f /tmp/centralpark.runtime.ok
iris session IRIS < /home/irisowner/central-park/iris-config/runtime.script
test -f /tmp/centralpark.runtime.ok
