module.exports = {
  apps: [
    {
      name: 'sodigaz-backend',
      cwd: '/home/debian/sodigaz-backend',
      script: '/home/debian/sodigaz-backend/venv/bin/uvicorn',
      args: 'app.main:app --host 0.0.0.0 --port 8000',
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        PYTHONPATH: '/home/debian/sodigaz-backend',
        DATABASE_URL: 'sqlite:///./gas_platform.db'
      },
      error_file: '/home/debian/sodigaz-backend/logs/error.log',
      out_file: '/home/debian/sodigaz-backend/logs/out.log',
      log_file: '/home/debian/sodigaz-backend/logs/combined.log',
      time: true
    },
    {
      name: 'sodigaz-backendv2',
      cwd: '/home/debian/apps/sodigaz-backend',
      script: '/home/debian/apps/sodigaz-backend/venv/bin/uvicorn',
      args: 'app.main:app --host 0.0.0.0 --port 8001',
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        PYTHONPATH: '/home/debian/apps/sodigaz-backend',
        DATABASE_URL: 'sqlite:///./gas_platform.db'
      },
      error_file: '/home/debian/apps/sodigaz-backend/logs/error.log',
      out_file: '/home/debian/apps/sodigaz-backend/logs/out.log',
      log_file: '/home/debian/apps/sodigaz-backend/logs/combined.log',
      time: true
    }
  ]
};
