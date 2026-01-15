import subprocess
import sys
import psutil
import logging
from threading import Lock

logger = logging.getLogger(__name__)

class ProcessManager:
    _instance = None
    _lock = Lock()
    _process = None

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(ProcessManager, cls).__new__(cls)
        return cls._instance

    def get_status(self):
        """Check if the process is running."""
        if self._process is None:
            return {"status": "stopped", "pid": None}
        
        # Check if process is still alive
        if self._process.poll() is None:
            return {"status": "running", "pid": self._process.pid}
        else:
            self._process = None
            return {"status": "stopped", "pid": None}

    def start_listener(self):
        """Start the listener process."""
        status = self.get_status()
        if status["status"] == "running":
            return {"status": "running", "pid": status["pid"], "message": "Already running"}

        try:
            # Run "python -m main"
            # We use sys.executable to ensure we use the same python interpreter
            cmd = [sys.executable, "-m", "main"]
            
            # Start process detached or just independent enough
            # On Windows, creationflags=subprocess.CREATE_NEW_CONSOLE might open a new window
            # We want it to run in background mostly, but capturing output might be tricky
            # For now, let's just run it.
            self._process = subprocess.Popen(
                cmd,
                cwd=sys.path[0], # Root of the project usually if we run from root
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0
            )
            
            logger.info(f"Started listener process with PID {self._process.pid}")
            return {"status": "running", "pid": self._process.pid, "message": "Started successfully"}
        except Exception as e:
            logger.error(f"Failed to start listener: {e}")
            return {"status": "error", "message": str(e)}

    def stop_listener(self):
        """Stop the listener process."""
        status = self.get_status()
        if status["status"] == "stopped":
            return {"status": "stopped", "message": "Already stopped"}

        try:
            # Kill process tree
            parent = psutil.Process(self._process.pid)
            for child in parent.children(recursive=True):
                child.terminate()
            parent.terminate()
            
            # Wait for meaningful termination
            gone, alive = psutil.wait_procs([parent], timeout=3)
            for p in alive:
                p.kill()
                
            self._process = None
            logger.info("Stopped listener process")
            return {"status": "stopped", "message": "Stopped successfully"}
        except Exception as e:
            logger.error(f"Failed to stop listener: {e}")
            # Force cleanup if checking failed
            self._process = None 
            return {"status": "error", "message": str(e)}

process_manager = ProcessManager()
