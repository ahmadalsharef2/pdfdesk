# Phase 7 — Action Wizard and batch processing

### The `.sequ` format

Foxit's actions are Adobe Acrobat workflow files. What the five shipped English files contain:

```
<Workflow xmlns="http://ns.adobe.com/acrobat/workflow/2012" title=… description=… majorVersion minorVersion>
  <Group label=…>                       one panel in the action pane
    <Instruction label=… pauseBefore/>  text shown to the user
    <Separator/>                        divider line
    <Command name=… pauseBefore promptUser>
      <Items>
        <Item name=… type=boolean|integer|text|string|atom|null value=…/>
        <Items name=…> … </Items>      nested group, e.g. SecuritySettings, LeaveAsIs
```

The parser must accept what the shipped files do:

- An optional UTF-8 BOM.
- CRLF, LF or CR-only line endings. `Action06.sequ` uses CR only.
- `MajorVersion` as well as `majorVersion`.
- Items whose `type` is `null` and that have no `value`.

The commands used in the shipped files:

| Command | pdfdesk feature |
|---|---|
| `RemoveHiddenInfo` | F46 |
| `COMP:AddWatermark` | F19 |
| `COMP:AddHeadFoot` | F18 |
| `WorkflowPlaybackSaveFiles` | save step (below) |
| `GeneralInfo` | F146 document properties |
| `OpenInfo` | F146 initial view |
| `Cpt:CapturePages` | F30 OCR |
| `Adobe:FindsFormFields` | F93 field recognition |
| `SetTabOrder` | F154 |
| `SetReadingLanguage` | F154 |
| `Adobe:MakeAccessible` | F154 auto-tag |
| `SetAlternateText` | F154 |
| `AccCheck:DoCheck` | F153 (32 of its 37 items switch single rules on or off) |
| `Annots:Tool:RedactMenuItem` | F40 |
| `Annots:Tool:ApplyRedactionsMenuItem` | F42 |
| `ReduceFileSize` | F34 |
| `DocSecurity` | F47 |
| `Scan:OPT` | F33 |
| `CALS:Preflight` | F60 / F61 |

### F80 Run an action

- **Foxit** (pp. 147–148): File > Action Wizard > Run Action, without needing an open file. A pane on the
  right lists the tasks. Add more files, folders or open files. Start. Steps with Prompt User open their
  dialog. A check mark appears on each finished task. Stop keeps what has been done; Resume continues.
  Done appears at the end. Shipped actions: Prepare for Distribution, Make Accessible, Publish Sensitive
  Information, Optimize Scanned Documents, Archive Documents.
- **pdfdesk:**
  - Each `Command` resolves to a registered command by its `.sequ` name. Its `Items` become the
    command's parameters. `promptUser` opens the command's dialog pre-filled. `pauseBefore` stops and
    waits for Continue.
  - The run goes file by file, and each file runs all steps in order.
  - An unknown command stops the run and names the command, rather than skipping it.
  - `WorkflowPlaybackSaveFiles` with `DocSaveDestType=WorkflowPlaybackSaveAs` asks once for an output
    folder and naming rule (F82).
- **Example:** before: C3 v1 and C4. After: Foxit's unmodified `Action01.sequ` (Prepare for
  Distribution), with the watermark and header/footer dialogs answered in the test. **Check:** both outputs
  have no comments, attachments, metadata or JavaScript, and they have the watermark and header.
  Bookmarks are kept, because `RmBookmarks=false`.
- **Example 2:** each of the five shipped files parses, and `Action03`, `05` and `06` run end to end on
  their matching corpus files: C3 v1 for `03`, C2 for `05`, C1 for `06`.
- **Open:** the full set of command names Foxit accepts, beyond the 19 above, so actions exported from
  Foxit or Acrobat also run. REA string search in `plugins/ActionWizard.fpi`.

### F81 Create and manage actions

- **Foxit** (pp. 147–149):
  - Create: files to process; commands moved from the left list to the right list and ordered;
    Specify Settings; Prompt User.
  - Layout: panels that can be renamed (Add Panel), instructions, dividers, Move Up/Down, Remove. Save
    with a name and description.
  - Manage: Edit, Rename, Copy, Remove, Move Up/Down, Import, Export.
- **pdfdesk:** an editor writing the same `.sequ` format. User actions are kept in
  `~/.local/share/pdfdesk/actions/`. Foxit's shipped actions can be imported, but are not copied into
  pdfdesk.
- **Example:** before: none. After: a new action "Bates and lock" (F21, then F47) saved and exported.
  **Check:** the exported file parses again to the same steps, and Foxit opens it (black-box: import it
  into Foxit's Manage Actions).

### F82 Shared batch dialog and output options

- **Foxit** (used by OCR, optimizer, Bates, header/footer, watermark, convert): Add Files, Add Folders,
  Add Open Files, drag and drop, Move Up/Down, Remove, "Remove unsupported files". Output Options:
  destination folder, naming (same name, or prefix/suffix), overwrite or not, log file.
- **pdfdesk:** one reusable widget plus one engine function: run a command over a list of files with
  these output options.
- **Example:** before: a folder with C3 v1, C4 and a `.txt` file. After: Add Folder offers "Remove
  unsupported files" for the `.txt`. The output gets suffix `_out`, and existing files are not
  overwritten. **Check:** output file names, and the log lists two files.
