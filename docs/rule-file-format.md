# Rule File Format Specification

`resource-leak-guard` uses YAML rule files to configure closeable resource types, release method patterns, and language-specific safe wrappers without altering tool source code.

## File Schema

```yaml
language: <language-name>  # e.g. java, go

acquisitions:
  - type: <TypeName>
    module: <module-name>
    factory_methods:
      - <Factory.methodName>

releases:
  - method: <close-method-name>

safe_wrappers:
  - ast_node_type: <tree-sitter-node-type>
    description: <human-readable-description>
```

## Adding Support for a New Language

To add support for a new language (e.g. Go, Python, C#):

1. **Create a new rule file**: Add `src/rules/<language>.yaml` following the schema above.
2. **Define Closeable Types**: List types whose constructors or factory methods allocate resources (e.g. `os.File` in Go).
3. **Define Release Methods**: List release method names (e.g. `Close` or `close` or `dispose`).
4. **Define Safe Wrappers**: Specify AST node types that indicate safe management (e.g. `defer_statement` in Go or `with_statement` in Python).
