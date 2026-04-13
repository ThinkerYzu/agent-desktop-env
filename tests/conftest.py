def pytest_addoption(parser):
    parser.addoption("--tab-id", type=int, default=70, help="Browser tab ID for the ADE app")
