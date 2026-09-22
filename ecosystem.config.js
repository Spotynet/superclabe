module.exports = {
  apps: [
    {
      name: "superclabe-api-dev",
      script: "/home/ubuntu/projects/apps/superclabe/webapp-spei-codi/backend/venv/bin/python",
      args: "-m uvicorn app.main:app --host 0.0.0.0 --port 3017",
      cwd: "/home/ubuntu/projects/apps/superclabe/webapp-spei-codi/backend",
      interpreter: "none",
      env: {
        DATABASE_URL: "postgresql://superclabe:bebe7ef907e8a566f140258faaa5d7fb@localhost:5432/webapp_spei",
        AES_SECRET_KEY: "c13dfcfa847823f0fba517c1b8ca05e3ccc4116d9f476cee9f7293be0413e2a3",
        JWT_SECRET: "8efe3033350efe682f2fec8ab7afb1955c32526844ff38d5282d498898b25d41",
        JWT_EXPIRE_MIN: "20",
      },
    },
  ],
};
