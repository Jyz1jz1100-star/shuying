import test from 'node:test';
import assert from 'node:assert/strict';
import { filterTasks, taskSource } from '../src/taskLibrary.ts';
import { sourceTarget } from '../src/topicOutline.ts';

const jobs=[
  {id:'web',title:'GPU Course',url:'https://example.org/lesson',author:'Alice',status:'completed'},
  {id:'sub',title:'采访',url:'',input_type:'srt',input_name:'interview.srt',status:'failed'},
  {id:'media',title:null,url:'',input_type:'media',input_name:'Podcast.wav',status:'transcribing'},
  {id:'cancel',url:'',input_type:'vtt',status:'canceled'},
];
test('search combines words and filters, retains source ordering',()=>{
  assert.deepEqual(filterTasks(jobs,' GPU  alice ','completed','url').map(j=>j.id),['web']);
  assert.deepEqual(filterTasks(jobs,'interview','attention','subtitle').map(j=>j.id),['sub']);
  assert.deepEqual(filterTasks(jobs,'','active','media').map(j=>j.id),['media']);
  assert.deepEqual(filterTasks(jobs,'','attention','all').map(j=>j.id),['sub','cancel']);
});
test('empty, missing fields, no match and source classification',()=>{
  assert.equal(filterTasks(jobs,'missing','all','all').length,0);
  assert.equal(filterTasks([],'','all','all').length,0);
  assert.equal(filterTasks(jobs,'','all','all').length,4);
  assert.equal(taskSource(jobs[3]),'subtitle');
  assert.equal(jobs[0].title,'GPU Course');
});
test('map navigation skips missing citations and never fabricates a target',()=>{
  const known=new Set(['s1','s2']);
  assert.equal(sourceTarget(['missing','s2','s1'],known),'s2');
  assert.equal(sourceTarget(['missing'],known),null);
  assert.equal(sourceTarget([],known),null);
  assert.equal(sourceTarget(['s1','s1'],known),'s1');
});
