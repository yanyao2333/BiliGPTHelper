"""在config模板发生更新时 及时无损合并用户的config"""
import ruamel.yaml

# TODO 保持原有格式和注释

yaml = ruamel.yaml.YAML()


def load_config(config_path):
    """加载config"""
    with open(config_path, encoding="utf-8") as f:
        config = yaml.load(f)
    return config


def is_have_diff(config, template):
    """判断用户的config是否有缺失"""
    for key in template:
        if key not in config:
            return True
        if isinstance(template[key], dict) and is_have_diff(config[key], template[key]):
            return True
    return False


def merge_config(config, template):
    """合并config 如果缺失，则加上这个键和对应默认值"""
    for key in template:
        if key not in config:
            config[key] = template[key]
        if isinstance(template[key], dict):
            merge_config(config[key], template[key])
    return config


def save_config(config, config_path):
    """保存config"""
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f)
