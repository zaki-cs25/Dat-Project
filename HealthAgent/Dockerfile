# IRIS for Health Community Edition. Ships FHIR R4, Interoperability, and IPM.
# No license file needed. We no longer install Python deps here, because the
# interview and care-plan worker run in a FastAPI sidecar.
ARG IMAGE=intersystemsdc/irishealth-community:latest-cd
FROM $IMAGE
USER root

WORKDIR /home/irisowner/central-park
COPY --chown=irisowner:irisowner . /home/irisowner/central-park

USER irisowner

# Boot-time setup: create the CENTRALPARK namespace, enable interop, load our
# classes, register the FHIR R4 endpoint and CSP REST app. iris.script writes /tmp/centralpark.bootstrap.ok on success and
# the test below asserts it, so a silent failure fails the build.
RUN mkdir -p /usr/irissys/mgr/centralpark \
    && iris start IRIS \
    && iris session IRIS < /home/irisowner/central-park/iris-config/iris.script \
    && test -f /tmp/centralpark.bootstrap.ok \
    && /usr/irissys/bin/irispython /home/irisowner/central-park/iris-config/check-fhir.py \
    && iris stop IRIS quietly
