# Loaded when the suite runs as a package (`unittest discover -s tests -t .`):
# no test may reach a real model, and none may change the protected
# directories. See tests/support.py.
from tests.support import install_offline_guard, record_state

install_offline_guard()
record_state()
