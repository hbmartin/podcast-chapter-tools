from llama_index import (
    GPTVectorStoreIndex,
    SimpleDirectoryReader,
    StorageContext,
    load_index_from_storage,
)

documents = SimpleDirectoryReader("podcasts-clean-transcripts").load_data()
index = GPTVectorStoreIndex.from_documents(documents)
index.storage_context.persist()


storage_context = StorageContext.from_defaults(persist_dir="./storage")
index = load_index_from_storage(storage_context)
