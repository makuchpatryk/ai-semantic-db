from dataclasses import dataclass

from semantic_db.application.ports import CollectionRepository, RecordRepository
from semantic_db.domain.errors import CollectionNotFoundError, RecordNotFoundError


@dataclass(frozen=True)
class DeleteRecordCommand:
    collection_name: str
    record_id: int


class DeleteRecord:
    def __init__(self, collections: CollectionRepository, records: RecordRepository) -> None:
        self._collections = collections
        self._records = records

    async def execute(self, cmd: DeleteRecordCommand) -> None:
        collection = await self._collections.get(cmd.collection_name)
        if collection is None or collection.id is None:
            raise CollectionNotFoundError(cmd.collection_name)

        # A bare DELETE matching 0 rows gives no signal, so check existence first.
        record = await self._records.get(collection.id, cmd.record_id)
        if record is None:
            raise RecordNotFoundError(cmd.collection_name, cmd.record_id)

        await self._records.delete(collection.id, cmd.record_id)
