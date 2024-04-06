# djraj-proj

Introduction to Software Engineering Project

## Git Repository Layout

- `forums` - Main python package. All Python code should live in here.
- `forums/main.py` - This is the file that is run to start the application. See below for details.
- `static` - Web resources that are served under the /static route inside the application.
- `templates` - HTML template files called by the application while rendering the application's pages.
- `poetry.lock`, `pyproject.toml` - These files are used by poetry to manage dependency versions.
- `.gitignore` - Defines what items should not be committed into git. 
- `up.sql` - DDL commands that can be used to initialize a database for use with the application
- `README.md` - You are here.

## Setting up your Environment

Install [Python 3](https://www.python.org/downloads/) and ensure that the `python` and `pip` binaries are available in your PATH before beginning.

I've set the project up using Poetry to simplify dependency management, so install that as well:

```shell
pip install --user poetry
```

Confirm that poetry is available:

```
poetry -V
```

If you see something like "Poetry (version 1.7.1)" then it is installed correctly. 

## Configuration

The application looks for its configuration file at the path in the environment variable `FORUMS_CONFIG` if it is set. If it is not set, it looks for `config.toml` in the process working directory, which is usually the git repository root.

Before starting the application, ensure that the file exists. You can paste the sample configuration below and make any necessary changes:

```toml
# Address and port to listen on.
listen_ip = "127.0.0.1"
listen_port = 8080

[db]
# The DB server to connect to
host = "IP_OR_HOSTNAME_HERE"
# The TCP/IP port to use to connect
port = 3306
# DB username and pw
user = "forums"
password = "PASSWORDHERE"
# the name of the mysql database to use
db = "forums"
```

## Running the Application

To start the application, run the following command:

```shell
poetry run python -m forums.main
```

Open a browser, and navigate to the URL given by the application. The default is [http://127.0.0.1:8080/](http://127.0.0.1:8080/).