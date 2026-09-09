# Workflow notes

1. Make the system reviewer's skill explicit about its rules and procedures. Organize it around worker usage, file merging, approval rules, conflict resolution, and how to use metadata such as identity, job role, and the author's subject expertise.
2. Track changes and provide an API so agents can inspect document versions.
3. Define rules and skills for each workflow case. For example, when two users edit the same file, publishing the first change advances its version. The second user's target still references the older version, creating a stale-base or conflict case.
 
