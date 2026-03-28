"""Configuration for hybrid cloud auto-scaling."""

PROMETHEUS_URL = "http://localhost:9090/api/v1/query"
THRESHOLD = 75.0
CHECK_INTERVAL = 30  # seconds

AWS_REGION = "us-east-1"
AMI_ID = "ami-00de3875b03809ec5"  # Ubuntu 22.04 LTS (us-east-1, 2026-03-20)
INSTANCE_TYPE = "t2.micro"
KEY_NAME = "mh-vm1"
SECURITY_GROUP = "sg-0312567d5a5a9df6d"

INSTANCE_NAME_TAG = "AutoScaled-from-LocalVM"
