REVOKE ALL ON SCHEMA agent FROM PUBLIC;
GRANT USAGE ON SCHEMA agent TO agent_runtime;

REVOKE ALL ON ALL TABLES IN SCHEMA agent FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA agent FROM agent_runtime;

GRANT SELECT, INSERT, UPDATE, DELETE
    ON TABLE agent.a2ui_message,
             agent.agent_run,
             agent.chat_command,
             agent.chat_interrupt,
             agent.chat_session,
             agent.chat_timeline_entry,
             agent."mastra_messages",
             agent."mastra_observational_memory",
             agent."mastra_resources",
             agent."mastra_threads",
             agent."mastra_workflow_snapshot"
    TO agent_runtime;
GRANT USAGE, SELECT
    ON SEQUENCE agent.chat_timeline_entry_sequence_seq
    TO agent_runtime;
GRANT SELECT ON TABLE agent.schema_contract TO agent_runtime;
