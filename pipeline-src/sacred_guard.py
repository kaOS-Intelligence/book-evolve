"""No-op guard stub for the standalone book-evolve pipeline.

The full Sacred Boundary guard is Sovereign-internal and is not shipped
with the public package. These no-ops keep the pipeline imports working.
"""
class SacredGuardError(RuntimeError):
    pass

class GuardTrip:
    def __init__(self, reason, token):
        self.reason = reason
        self.token = token

def check_paths(*args, **kwargs):
    pass

def check_text(*args, **kwargs):
    pass

def check_candidate(*args, **kwargs):
    pass

def guard_inputs(*args, **kwargs):
    pass
