# Banyan: Entities and Methods

# Overview:

Banyan is yet another Taxonomy management project intended as an open source starter for organizations needing semantic master data management tooling.

CS Model:  
Directed Acyclic Graph

Knowlege Management Modeling:  
Taxonomy/Vocabulary

Persistence:  
Relational database with recursive support

# 

# Entities

Core entity types are Graph, Node, Link

## Graph

(aka Taxonomy/Vocabulary)  
The graph is both a simple object and a concept representing the whole of an integrated collection of Nodes and Links (see below) Operations (methods) to a Graph may (CRUD) may be understood as being against the simple entity or against the totality of the conceptual graph: E.g. Export.

CREATE TABLE \`graph\` (  
  \`graph\_id\` UUID,  
  \`name\` character varying(200),  
  \`notes\` character varying(max),  
  \`topology\_id\` int,  
  \`root\_node\_id\` uuid,  
  \`inserted\_datetime\` datetime,  
  \`updated\_datetime\` datetime,  
  \`updated\_by\` character varying(200),  
  KEY \`Key\` (\`graph\_id\`)  
);

## Node 

(aka Term)  
Nodes generally represent concepts at some level of specificity but sometimes have largely structural functions those these structural nodes imply a  semantic scope in almost all cases.  
Nodes have both global identity and graph-local identity.    
In this modeling nodes belong to a graph but can be referenced across graphs. Past implementations have featured nodes as free agents and only tethered to a graph (taxonomy) by way of relationships but this flexibility is often a liability and has rarely if even been a big feature (reuse of nodes across graphs).

CREATE TABLE \`node\` (  
  \`node\_id\` uniqueidentifier,  
  \`node\_type\_id\` int,  
  ‘Graph\_id’ uuid,  
  \`source\_id\` character varying(200),  
  \`name\` character varying(200),  
  \`notes\` character varying(200),  
  \`metadata\` character varying(max),  
  \`inserted\_datetime\` datetime,  
  \`updated\_datetime\` datetime,  
  \`updated\_by\` character varying(200),  
  KEY \`Key\` (\`node\_id\`)  
);

## Link 

Aka: relationship, edge

Links, commonly called edges in CS DAG terminology, are directional (mostly) vectors that express semantic connection between nodes.  Links can be typed which lends the link semantic significance to express the nature of relationship.

CREATE TABLE \`link\` (  
  \`link\_id\` uuid,  
  \`link\_type\_id\` int,  
  \`from\_graph\_id\` uuid,  
  \`to\_graph\_id\` uuid,  
  \`from\_node\` uuid,  
  \`to\_node\` uuid,  
  \`link\_order\` float, – Fractional ordering for easy inserts/moves  
  \`metadata\` character varying(max),  
  \`valid\_from\_datetime\` datetime,  
  \`valid\_until\_datetime\` datetime,  
  \`is\_disabled\` bit,  
  \`inserted\_datetime\` datetime,  
  \`updated\_datetime\` datetime,  
  \`updated\_by\` character varying(200),  
  KEY \`Key\` (\`link\_id\`)  
);

## 

## Meta-Entity types

### Link Type

Links express relative meaning relative to the origin and destination node.  
Generally we pre-seed the link-type hierarchy with 3 fundamental link-type classes:  
HIERARCHICAL, SYNONYM, RELATED

Of the three, RELATED type links are allowed to have from graph and to-graph not be equal but HIERARCHICAL and SYNONYM type links must have references only within the same graph.

Within these constraints, relationships can be defined to meet whatever semantic purpose the modeler needs.  Links themselves may carry semantic information and the link type can control the schema of the link metadata attribute.

CREATE TABLE \`link\_type\` (  
  \`link\_type\_id\` int,  
  \`\` \<type\>,  
  \`parent\_link\_type\` int,  
  \`name\` character varying(200),  
  \`notes\` character varying(max),  
  \`metadata\_schema\` character varying(max),  
  \`inserted\_datetime\` datetime,  
  \`updated\_datetime\` datetime,  
  \`updated\_by\` character varying(200),  
  KEY \`Key\` (\`link\_type\_id\`)  
);

### Node Type

The schema of nodes is intentionally very simple and generic but node-type allows customization of additional metadata attributes to elaborate the specifics of a given node type.

### Graph Topology

It may be desirable to apply specific constraints to the topology of a graph in order to enforce master design constraints.  E.g. poly hierarchy or simple hierarchy, depth etc.  This relatively unelaborated meta-object is intended as the mechanism to define these constraints.  A graph is assigned a topology type as a means to constrain it’s shape.  Changing topology after creation and construction is fraught and may require a comprehensive audit of the structure before a change  can be made.  TBD

Associative Entity Types

Practical considerations of how a node may be related to business objects should be considered. Can this be modeled for in a completely generic manner other than using (for example) synonym nodes as proxies for external \-non-managed business entities.  Food for thought.

# Methods

Actions/methods/verbs to be applied to the entities defined above.

Graph

* ADD  
* CLONE  
* UPDATE  
* DELETE  
* GET (by id)  
* LIST  
* IMPORT  
* EXPORT  
* DIFF  
* BATCH  
* CHECKPOINT  
* RESTORE  
* QUERY \- graph-traversal query language (not OWL\!)


NODE

* ADD  
* UPDATE  
* DELETE  
* GET (by id)  
* QUERY \- query nodes by attributes  
* SPLIT \-   
* JOIN  
* MOVE (sugar for update link)  
* ORDER (relative to parent, top, bottom, absolute, relative) (also sugar for link update/bach)

LINK

* ADD/UPSERT  
* UPDATE  
* DELETE  
* GET (by id)

