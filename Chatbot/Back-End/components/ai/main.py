import json
from threading import *
from haystack import Document
from haystack.nodes.retriever import TableTextRetriever
from haystack.document_stores import InMemoryDocumentStore
from haystack.nodes import TableReader


class Ai:
    def __init__(self, data, output_buffer):
        self.output_buffer = output_buffer
        self.tables = data
        self.retriever = None
        self.reader = None
        self.document_index = "document"
        self.document_store = InMemoryDocumentStore(embedding_dim=512)
        self.processedTables = []
        self.ai_processes = []
        self.__processInfo()
        self.__initPipeline()

    def updateData(self, data):
        while self.__len__() > 0:  # wait for current requests to complete
            self.clear_dead_processes()
        self.document_store = InMemoryDocumentStore(embedding_dim=512)
        self.processedTables = []
        self.tables = data
        self.__processInfo()
        self.__initPipeline()

    def __processInfo(self):
        # Add the tables to the DocumentStore.
        self.output_buffer.put(json.dumps({"type": "update",
                                           "component": "ai",
                                           "update": "busy",
                                           "update_message": "Processing Documents"
                                           }))
        for key, table in self.tables.items():
            current_df = table["df"]
            current_doc_title = table["title"]
            current_section_title = table["section_title"]
            document = Document(
                content=current_df,
                content_type="table",
                meta={"title": current_doc_title, "section_title": current_section_title, "url": table["url"]},
                id=key,
            )
            self.processedTables.append(document)
        self.document_store.write_documents(self.processedTables, index="document")

    def __initPipeline(self):
        self.output_buffer.put(json.dumps({"type": "update",
                                           "component": "ai",
                                           "update": "busy",
                                           "update_message": "Initializing Pipeline"
                                           }))
        self.retriever = TableTextRetriever(
            document_store=self.document_store,
            query_embedding_model="deepset/bert-small-mm_retrieval-question_encoder",
            passage_embedding_model="deepset/bert-small-mm_retrieval-passage_encoder",
            table_embedding_model="deepset/bert-small-mm_retrieval-table_encoder",
            embed_meta_fields=["title", "section_title"],
        )

        # Add table embeddings to the tables in DocumentStore
        self.document_store.update_embeddings(retriever=self.retriever)
        self.reader = TableReader(model_name_or_path="google/tapas-large-finetuned-sqa", max_seq_len=512)
        self.output_buffer.put(json.dumps({"type": "update",
                                           "component": "ai",
                                           "update": "working",
                                           "update_message": "Ai Initialized"
                                           }))

    def clear_dead_processes(self):
        # only keep the alive processes
        self.ai_processes = [ai_process for ai_process in self.ai_processes if ai_process.is_alive()]

    def __len__(self):
        self.clear_dead_processes()
        return len(self.ai_processes)

    def ask(self, request, join):
        msg_id, query = request
        if join:
            self.ai_processes[0].join()
            self.clear_dead_processes()
        ai_thread = Thread(target=self.run, args=[query, msg_id, self.output_buffer])
        ai_thread.start()
        self.ai_processes.append(ai_thread)

    def run(self, query, msg_id, output_buffer):
        # print(query, msg_id, output_buffer)
        try:
            if query is not None:
                retrieved_tables = self.retriever.retrieve(query, top_k=5)
                # Get highest scored table
                if len(retrieved_tables) > 0:
                    # print(retrieved_tables[0].id)
                    table_doc = self.document_store.get_document_by_id(retrieved_tables[0].id)
                    prediction = self.reader.predict(query=query, documents=[table_doc])
                    output = {"type": "ai_query",
                              "id": msg_id,
                              "url": table_doc.meta["url"],
                              "title": table_doc.meta["title"],
                              "answer": " ".join([obj.answer for obj in prediction["answers"]])
                              }
                    output_buffer.put(json.dumps(output))
        except:
            output = {"type": "ai_query",
                      "id": msg_id,
                      "url": "N/A",
                      "title": "N/A",
                      "answer": "Sorry the ai cannot process this query"
                      }
            output_buffer.put(json.dumps(output))
