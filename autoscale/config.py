"""Configuration for hybrid cloud auto-scaling."""

PROMETHEUS_URL = "http://localhost:9090/api/v1/query"
THRESHOLD = 75.0
CHECK_INTERVAL = 30  # seconds

AWS_REGION = "ap-south-1"
AMI_ID = "ami-0c55b159cbfafe1f0"  # Update for your region
INSTANCE_TYPE = "t2.micro"
KEY_NAME = "your-key-pair"
SECURITY_GROUP = "sg-xxxxxxxx"

INSTANCE_NAME_TAG = "AutoScaled-from-LocalVM"
