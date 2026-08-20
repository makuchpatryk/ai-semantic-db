from semantic_db.domain.collection import CollectionSchema, FieldDefinition
from semantic_db.domain.field_types import FieldType

PRODUCTS = CollectionSchema(
    fields=(
        FieldDefinition(name="title", type=FieldType.TEXT, embed=True, required=True),
        FieldDefinition(name="description", type=FieldType.TEXT, embed=True),
        FieldDefinition(
            name="category",
            type=FieldType.ENUM,
            embed=True,
            enum_values=("pumps", "motors", "valves", "sensors"),
        ),
        FieldDefinition(name="year", type=FieldType.INT, embed=True),
        FieldDefinition(name="price", type=FieldType.FLOAT, embed=True, unit="PLN"),
    )
)

#: A deliberately different shape (PRD 12): exercises date and array<string>.
BOOKS = CollectionSchema(
    fields=(
        FieldDefinition(name="author", type=FieldType.TEXT, embed=True, required=True),
        FieldDefinition(name="published", type=FieldType.DATE, embed=True),
        FieldDefinition(name="genres", type=FieldType.ARRAY_STRING, embed=True),
        FieldDefinition(name="in_print", type=FieldType.BOOL, embed=True),
        FieldDefinition(name="shelf_code", type=FieldType.TEXT),
    )
)

PRODUCTS_FIELD_SPECS = [
    "title:text:embed,required",
    "description:text:embed",
    "category:enum(pumps|motors|valves|sensors):embed",
    "year:int:embed",
    "price:float:embed:unit=PLN",
]

BOOKS_FIELD_SPECS = [
    "author:text:embed,required",
    "published:date:embed",
    "genres:array<string>:embed",
    "in_print:bool:embed",
    "shelf_code:text",
]
