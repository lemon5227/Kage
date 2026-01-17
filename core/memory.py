import json
import uuid
import os
import json
import chromadb
import datetime

class MemorySystem:
    def __init__(self):
        current_file_path = os.path.abspath(__file__)
        core_dir = os.path.dirname(current_file_path)
        project_dir = os.path.dirname(core_dir)

        data_dir  = os.path.join(project_dir,"data")

        if not os.path.exists(data_dir):
            os.makedirs(data_dir)

        self.raw_log_file = os.path.join(data_dir,"raw_log.jsonl")
        self.chroma_db = os.path.join(data_dir,"chromadb")

        print(f"Memory is initialized at {data_dir}")

        # initialize chromadb
        self.client = chromadb.PersistentClient(path=self.chroma_db)
        self.collection = self.client.get_or_create_collection(name="kage_mind")

    def add_memory(self,content:str,emotion:str="neutral",emotion_conf:float=1.0,type:str = "chat",importance:int =1):
        """
        add a memory with emotion, emotion confidence, type, and importance
        """

        mem_id=str(uuid.uuid4())
        time_stamp = datetime.datetime.now().isoformat()
        
        # build a full memory entry
        full_memory_obj = {
            "id":mem_id,
            "timestamp":time_stamp,
            "content":content,
            "emotion_data":{
                "emotion":emotion,
                "emotion_conf":emotion_conf
            },
            "type":type,
            "importance":importance
        }  

        # write to raw log file 
        with open(self.raw_log_file,"a",encoding="utf-8") as f:
            f.write(json.dumps(full_memory_obj,ensure_ascii=False)+"\n")
        

        # add to chromadb
        # emotion not involved in chromadb but as a filter(metadata)

        metadata = {
            "type" :type,
            "importance":importance,
            "emotion":emotion, # emotion as a label
            "timestamp":time_stamp
        }

        self.collection.add(
            documents=[content],
            metadatas=[metadata],
            ids=[mem_id]
        )

        print(f"Memory loaded: {mem_id} emotion: {emotion} type: {type} importance: {importance}")

    def recall(self,query:str,filters:dict=None,n_result=3):
        #  at default, we don't filter by emotion, we return the result with emotion as a label
        query_args={
            "query_texts":[query],
            "n_results":n_result
        }


        # only filter by emotion if we need
        # when we say i only want to recall happy memories, we filter by emotion
        if filters:
            query_args["where"] = filters
        
        results = self.collection.query(**query_args)
        
        ## not only return the documents, but also return the metadata
        # {text + emotion}

        memories = []
        if results['documents']:
            for content,metadata in zip(results['documents'][0],results['metadatas'][0]):
                
                # build a clear information package
                
                memory_item = {
                    "content":content,
                    "emotion":metadata.get("emotion","neutral"),
                    "timestamp":metadata.get("timestamp","")
                }

                memories.append(memory_item)
        return memories