class GlobalVariablesManager:
    def __init__(self):
        self._variables = {}
        self._read_only_variables = set()

    def set_variable(self, key, value, read_only=False):
        if key in self._read_only_variables:
            raise PermissionError(f"{key} 是只读变量，不能修改。")
        self._variables[key] = value
        if read_only:
            self._read_only_variables.add(key)

    def get_variable(self, key):
        return self._variables.get(key, None)

    def is_read_only(self, key):
        return key in self._read_only_variables

    def set_from_dict(self, data: dict):
        for key, value in data.items():
            self.set_variable(key, value)
