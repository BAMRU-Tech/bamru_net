from bamru_net.tracing import setup_tracing


def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)

    # setup_tracing()
