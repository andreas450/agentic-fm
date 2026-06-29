# Find Requests (Specify Find Requests Dialog)

Shared reference for the Query structure used by Enter Find Mode, Perform Find, Constrain Found Set, and Extend Found Set.

## Query XML Structure

```xml
<Query>
  <RequestRow operation="Include">
    <Criteria>
      <Field table="" id="0" name=""/>
      <Text>search value</Text>
    </Criteria>
  </RequestRow>
</Query>
```

### RequestRow

- `operation`: `"Include"` (find matching) | `"Exclude"` (omit matching)
- Multiple RequestRow elements act as OR conditions (separate find requests)
- Multiple Criteria elements within a single RequestRow act as AND conditions (same request, multiple fields)

### Field

- Standard field reference: `table`, `id`, `name` attributes
- Optional `repetition` attribute for repeating fields (e.g., `repetition="2"`)

### Text

- Contains the search value — can be a literal value, a variable (`$variable`), or a pattern using search operators

## Search Operators

| Operator | Meaning |
|----------|---------|
| `=` | Match whole word (or match empty) |
| `==` | Match entire field |
| `!` | Find duplicate values |
| `<` | Less than |
| `≤` | Less than or equal |
| `>` | Greater than |
| `≥` | Greater than or equal |
| `...` | Range (e.g., `1...100`) |
| `//` | Today's date |
| `?` | Invalid date or time |
| `@` | Any one character |
| `#` | Any one digit |
| `*` | Zero or more characters |
| `\` | Escape next character |
| `""` | Match phrase (from word start) |
| `*""` | Match phrase (from anywhere) |
| `~` | Relaxed search (Japanese only) |

## Variable Notes

- A variable can hold a simple pattern (e.g., `*/*/$year`) or a fully-formed expression (e.g., `$dateMatch` whose value is `*/*/2026`)
- Repetition index syntax (`$variable[repetition]`) is not supported inside find request variables
- Nested variables (a variable whose value contains another variable reference) are not evaluated correctly
- When a variable appears in a file path context, use `/` or `:` as the terminator character

## HR Parameters

- **Restore** — HR shows "Restore" as a flag when `state="True"`; omitted when `state="False"`
- **Find without indexes** — HR shows "Find without indexes" when `Option state="True"`; omitted when `state="False"`. Only available on Constrain Found Set.

## HR Representation of the Query (converter grammar — G3)

The converter renders the whole `<Query>` subtree as a single labelled HR parameter, `Find Requests: <value>` (the `findRequests` grammar primitive in `catalog_converter.cpp`).
An absent or empty Query emits no parameter at all.

The `<value>` grammar:

- **Rows** (each `<RequestRow>`, OR-combined) are separated by ` | `.
- A row prefixed `Omit ` is `operation="Exclude"` (omit matching records); otherwise `operation="Include"`.
- **Criteria** within a row (AND-combined, same request) are separated by ` & `.
- Each criterion is `<fieldref>: <text>` when field-scoped, or a bare `<text>` when field-less (FM's empty `<Field table="" id="0" name=""/>`).
- `<fieldref>` is a `Table::Field` reference resolved through the active context; `<text>` is the literal search value, variable, or search-operator pattern, XML-escaped on emit.

Examples:

| HR | Meaning |
|----|---------|
| `Find Requests: $query` | one field-less request whose value is the variable `$query` |
| `Find Requests: Customers::Name: Smith & Customers::City: NYC` | one request, two criteria (AND) |
| `Find Requests: Customers::Status: Active \| Omit Customers::Status: Closed` | two requests (OR): find Active, omit Closed |
| `Find Requests: >100` | field-less request using the `>` search operator |

Known limitations (documented, rare in practice): a field-less search value containing a literal ` : ` (space-colon-space), ` | `, or ` & ` will be mis-split; the field `repetition` attribute is not yet modelled.

## Steps Using This Structure

- Enter Find Mode — has Pause and Restore (no Option)
- Perform Find — has Restore only (no Option or Pause)
- Constrain Found Set — has Restore and Option (find without indexes)
- Extend Found Set — has Restore only (no Option)
