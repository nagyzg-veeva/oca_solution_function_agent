I'm planning an agentic application for the following use case. Help me to design the application:

The problem: My company is Veeva. One of Veeva's products is a CRM that originally was developed on the top of the Salesforce platforms, called Veeva CRM. 
Veeva recently decided to reimplement the CRM functionality on its on application platform, called Veeva Vault. The name of the new product is Veeva Vault CRM 

As a consequence of this decision, Veeva now migratin existing customers from the Salesforce-based Veeva CRM to the Vault-based Vault CRM.

The migration of the Data model and the Out-of-the-box functionality is covered by the Veeva product team.

As part of the migration, custom functionalities, developed specifically for a particular Veeva CRM environments have also to be migrated, reimplemented.

This Veeva CRM customizations are including the following Salesforce components:
- Apex code
- Flows and Process builders
- Visualforce solutions 
- Lightning solutions

We developed an "assessmet" process that reveals all the custom componenst in a Salesforce org forllowing the process of:
1. extraxting all custom components
2. extraxting all the data model elements - object, fields . which the custom components are dependent on. 
3. we store the data model dependencies of the components. This tells us, for example,  what object and fields a trigger is operation on
4. we extreact he cross component dependencies. We build a DAG (graph) out of this dependencies. We know wwhich components are relying on each other, ultimatelly 
we see what components are working together to fullfill a task 
5. we group the component into technical groups, we call these Component Group. A component group is a community of components working together doing somethinc. 
e.g: a trigger a ttrigger handler class and a trigger helper class belongs to a component group.
6. All Component Gropups get a meaningfull description that explains what the purpose the particular group serves


The next step of the process is formulating business functionalities out of the component groups. 
Why? as we need to migrate the functionalities from one platform to another (Salesforce -> Vault), simple reimplementing the technical functionalities won't work, The two platforms
work different ways and the the functionalities can cat be mapped at a component level

Instead we need to understand the business functionalities what these components are serving, so the migration will happen on a top-to.bottom manner.
A Solution Function is a business functionality that is composed of one or more component gorups. the Solution Function focuses on the functionality instead of the implementation details.

I want to develop an LLM-based agentic application that is able to formulate these Solution Functions. 

Help me to lay down the basic concept and the fundsmentals of the architecure of an application like this.
Answer the following quesions:
- What context the application would need to cover the requirement
- What agent component would be needed : eg. solution function builder, reflection/ validator agent etc

The prefered platform for the solution is LangGraph