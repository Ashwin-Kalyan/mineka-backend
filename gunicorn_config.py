import os

# Server socket
bind = f"0.0.0.0:{os.getenv('PORT', '3000')}"

# Worker processes
workers = 2
worker_class = "sync"

# Timeouts
timeout = 120
keepalive = 2

# Logging
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stdout
loglevel = "info"

# Process naming
proc_name = "mineka-booking-api"

# Worker settings
max_requests = 1000
max_requests_jitter = 50

# SSL (if needed)
# keyfile = "/path/to/key.pem"
# certfile = "/path/to/cert.pem"