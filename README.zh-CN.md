# csv-relation-check 中文说明

导入数据前，离线校验多个 CSV 的主键、唯一键、复合外键、必填字段与行宽。仅需 Python 3.10+，无第三方运行时依赖。

```sh
python -m pip install .
python -m csv_relation_check examples/contract.json --json
python -m csv_relation_check examples/broken-contract.json --json
```

第一条检查应退出 0，第二条应退出 1，并报告重复订单编号与缺失的客户外键。标识符按原始字符串比较：`001` 与 `1` 不同，大小写、空格和 Unicode 表示不会被自动归一化。

用 JSON 明确声明表、CSV 路径和关系。路径默认相对于契约文件目录，`--root` 可切换数据根目录。使用临时 SQLite 文件进行索引与关联检查，不把整份数据放进 Python 集合；输出仅含表名、列名和逻辑记录序号，不含数据单元格原值。默认详细样例上限为 100，完整计数不受影响。

退出码 2 表示参数、文件、编码、解析或资源限制错误，不能视为完整检查。只支持 UTF-8 CSV/TSV；不做类型推断、转换或修复。空字符串具有明确规则：主键不能为空，空白字符不自动裁剪，可选外键只有所有分量均为空时才跳过。

临时数据库会存储原值，正常结束和异常退出时清理，但不承诺安全擦除或强制杀进程后的清理。可通过 `--temp-dir` 指定合适的临时磁盘。完整安装、契约、限制、测试和清理说明见 [英文 README](README.md)。卸载：`python -m pip uninstall csv-relation-check`。
