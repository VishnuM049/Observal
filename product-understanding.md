Observal Spec Doc

Description:

Organizations need a centralized platform for uploading, observing and improving their MCP servers and agents.

This platform is specifically made for engineering teams to monitor MCP servers and Agents created for use with IDE’s and Agentic-CLIs

Usecase:

Teams(AI developers) keep creating agents and MCP servers for the organization. They face challenges in 
Distribution & Adoption -> I create an MCP/AGENT and I want to publish it to a marketplace
Standardization -> Enterprises want only standardized MCP/AGENT in the marketplace, with uniform description and other fields
Observability -> I have no Idea how well my MCP/AGENT performs for my users or how they are using it. Eg: it should return code acceptance
Iteration & Improvement -> I have no idea on which aspect of my agent/mcp to improve or where the bottleneck is eg: Prompt, RAG efficiency. (SLM as a judge comes in here) 
Feedback-> I have no portal to see how users react to my product


Why not orgs build it in house:

Orgs will have to dedicate a separate team to create and maintain this market place. AI evolves fast, IDEs and CLIs keep changing, our platform provides support of all the IDE, CLI and provides updates.

Additionally you need significant R&D to train and manage a SLM which will intake your product description and compare it against usage to find inefficiencies in your product.

TL;DR companies can do it on their own but they need to put up their own team and keep the product up to date which is a hassle, so we can do it.

User Flow:

Glossary(read:very imp)
Enterprise -> The customer we are serving
MCP servers/Agents -> AI tooling especially created to be used with Agentic CLI/IDE like Cursor, Kiro, Claude code, Antigravity, Gemini CLI etc
Developers -> AI developers who create MCP servers or AI agents
Users -> Also developers but they are the people who consume the MCP or Agents by integrating them in their daily development workflow
Customer -> Customers of the organization we are serving


Steps


Step1: Enterprise Sets up the Server (Can self host), Observal can be installed easily using docker pretty much anywhere

Step2: follow one of the below steps depending

1) MCP Registry

Developers can submit repo to this server with
/submit <GIT_URL>


Observal have an automated process to evaluate the MCP server (Check for necessary details) And upload it, 

Users can install this MCP server to any agent in the form of a config file with a download button.

The prompt should then give setup steps for the users to use this MCP servers.

We will track the number of downloads and calls for these MCP servers.
Here we will also document the MCPserver and its purpose

2) AGENT Registry


Developers can submit repo to this server with
/submit <GIT_URL>

We have an automated process to evaluate the Agent.
we will also document the agent, it’s purpose etc

Note: Agent is just Prompt + MCPs + Model file

Agent performance in production will be evaluated using SLM as a judge. The performance will be scored based on code acceptance, tool call failures, tool calls, thought process. Etc  
 
