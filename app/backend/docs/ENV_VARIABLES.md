# Environment Variables

This document describes all environment variables used by the application.

## Azure OpenAI Configuration

- `AZURE_OPENAI_API_KEY`: API key for Azure OpenAI
- `AZURE_OPENAI_ENDPOINT`: Endpoint URL for Azure OpenAI
- `AZURE_OPENAI_REALTIME_DEPLOYMENT`: Deployment name for Realtime API
- `AZURE_OPENAI_REALTIME_VOICE_CHOICE`: Voice to use (defaults to "coral")

## Azure AI Search Configuration

- `AZURE_SEARCH_API_KEY`: API key for Azure AI Search
- `AZURE_SEARCH_ENDPOINT`: Endpoint URL for Azure AI Search
- `AZURE_SEARCH_INDEX`: Name of the search index
- `AZURE_SEARCH_SEMANTIC_CONFIGURATION`: Optional configuration for semantic search
- `AZURE_SEARCH_IDENTIFIER_FIELD`: Field name for document IDs (defaults to "chunk_id")
- `AZURE_SEARCH_CONTENT_FIELD`: Field name for content (defaults to "chunk")
- `AZURE_SEARCH_EMBEDDING_FIELD`: Field name for embeddings (defaults to "text_vector")
- `AZURE_SEARCH_TITLE_FIELD`: Field name for titles (defaults to "title")
- `AZURE_SEARCH_USE_VECTOR_QUERY`: Whether to use vector search (defaults to "true")

## Azure Storage Configuration

- `AZURE_STORAGE_ENDPOINT`: Endpoint URL for Azure Storage
- `AZURE_STORAGE_CONNECTION_STRING`: Connection string for Azure Storage
- `AZURE_STORAGE_CONTAINER`: Name of the storage container

## Auth0 Logs API Configuration

- `AUTH0_LOGS_ENDPOINT`: Endpoint URL for Auth0 logs API (defaults to "https://func-auth0logs-001.azurewebsites.net/api/member_proxy")
- `AUTH0_LOGS_API_KEY`: API key for Auth0 logs API (required for accessing Auth0 logs)

## Authentication

- `AZURE_TENANT_ID`: Azure tenant ID for authentication
- `RUNNING_IN_PRODUCTION`: Set to any value in production to skip loading .env file