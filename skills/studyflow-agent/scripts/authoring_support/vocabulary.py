from __future__ import annotations
import base64
import csv
import io
import json
import re
import unicodedata
from .paths import digest


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC",value).casefold().split())


def catalog(workspace, declarations):
    entries=[];sources=[];seen=set();identities=set()
    if not 1<=len(declarations)<=8:
        raise ValueError("SOURCE_ID: provide one to eight explicitly named TSV sources")
    for identifier,relative in declarations:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}",identifier) or identifier in seen:
            raise ValueError("SOURCE_ID: identifiers must be unique and stable")
        seen.add(identifier);path=workspace.path(relative)
        if path.suffix.lower() not in {".tsv",".txt"}:
            raise ValueError("SOURCE_FORMAT: only explicitly selected TSV/TXT material")
        raw=path.read_bytes()
        if len(raw)>16*1024*1024:
            raise ValueError("INPUT_BUDGET: source exceeds 16 MiB")
        import hashlib
        source_hash=hashlib.sha256(raw).hexdigest()
        reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")),delimiter="\t")
        fields=reader.fieldnames or []
        aliases={"word":"word","phonetic":"phonetic" if "phonetic" in fields else "音标","meaning":"meaning" if "meaning" in fields else "释义","origin":"origin" if "origin" in fields else "来源"}
        if any(field not in fields for field in aliases.values()) or len(fields)!=len(set(fields)):
            raise ValueError("SOURCE_FORMAT: require word/phonetic/meaning/origin columns (Chinese aliases allowed)")
        words=set();count=0
        for line,row in enumerate(reader,2):
            if None in row or any(row.get(field) is None for field in aliases.values()):
                raise ValueError("SOURCE_FORMAT: malformed TSV row")
            values={key:row[field] for key,field in aliases.items()}
            word=values["word"]
            if not word or word!=word.strip() or word in words:
                raise ValueError("DUPLICATE_ENTRY: blank, untrimmed or repeated source spelling")
            words.add(word);count+=1
            entry_id="v-"+digest([identifier,unicodedata.normalize("NFC",word)])[:32]
            if entry_id in identities:raise ValueError("DUPLICATE_ENTRY: normalized source identities collide")
            identities.add(entry_id)
            entries.append({"entry_id":entry_id,"source_id":identifier,"source_line":line,**values})
        sources.append({"id":identifier,"path":path.relative_to(workspace.root).as_posix(),"sha256":source_hash,"records":count})
    return entries,sources


def query(workspace,args):
    if not args.word and not args.contains and not args.browse:
        raise ValueError("QUERY_REQUIRED: specify words, a narrow text filter, or intentional candidate browsing")
    if args.browse and not args.purpose:
        raise ValueError("QUERY_REQUIRED: browsing requires a finite purpose")
    if not 1<=args.limit<=60 or not 1000<=args.max_chars<=32000:
        raise ValueError("OUTPUT_BUDGET: limit 1..60 and max_chars 1000..32000")
    entries,sources=catalog(workspace,args.source)
    words={normalized(word) for word in args.word}
    filters={"words":sorted(words),"contains":normalized(args.contains or ""),"browse":args.browse,"purpose":args.purpose,"limit":args.limit,"max_chars":args.max_chars}
    excluded=set()
    if args.exclude_selections_dir:
        from .selections import selected_state
        state=selected_state(workspace,args.exclude_selections_dir,sources)
        excluded=state["ids"];filters["selection_fingerprint"]=state["fingerprint"]
        filters["selection_directory"]=args.exclude_selections_dir
    scope=digest([sources,filters]);offset=0
    if args.cursor:
        try:
            decoded=json.loads(base64.urlsafe_b64decode(args.cursor.encode("ascii")))
            if decoded["scope"]!=scope or type(decoded["offset"]) is not int or decoded["offset"]<0:
                raise ValueError()
            offset=decoded["offset"]
        except (ValueError,KeyError,TypeError,UnicodeError):
            raise ValueError("CURSOR_MISMATCH: source version or query changed") from None
    matching=[e for e in entries if e["entry_id"] not in excluded and (not words or normalized(e["word"]) in words) and (not filters["contains"] or filters["contains"] in normalized(e["word"]+" "+e["meaning"]))]
    if offset>len(matching):
        raise ValueError("CURSOR_MISMATCH: invalid offset")
    page=[]
    result={"ok":True,"sources":sources,"items":page,"matched_records":len(matching),"next_cursor":None,"learning_mastery":"not_inferred"}
    for entry in matching[offset:offset+args.limit]:
        candidate={**result,"items":[*page,entry],"next_cursor":"x"*192}
        if len(json.dumps(candidate,ensure_ascii=False))>args.max_chars:
            if not page:
                raise ValueError("OUTPUT_BUDGET: one entry cannot fit; increase budget, never truncate its definition")
            break
        page.append(entry)
    following=offset+len(page)
    if following<len(matching):
        result["next_cursor"]=base64.urlsafe_b64encode(json.dumps({"scope":scope,"offset":following},separators=(",",":")).encode()).decode()
    if len(json.dumps(result,ensure_ascii=False))>args.max_chars:
        raise ValueError("OUTPUT_BUDGET: response metadata exceeds budget")
    return result
