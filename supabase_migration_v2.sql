-- 비둘기 서비스 2차 설정 (게스트 · 마스터 · 개인/단체방)
-- supabase_schema.sql을 이미 실행한 프로젝트에서, SQL Editor에 붙여 넣고 Run을 한 번 누릅니다.
-- 여러 번 실행해도 안전합니다.

-- 구조: 칸 2개 추가 + 새 테이블 3개 / 이유: 비밀 메시지는 칸 하나, 방 삭제는 cascade로 해결
-- 게스트 이름과 새 방 id를 받을 수 있도록 messages의 고정 목록 제한을 푼다.
alter table public.messages drop constraint if exists messages_room_check;
alter table public.messages drop constraint if exists messages_sender_check;

-- sender_id: 말풍선 주인(멤버·마스터는 이름, 게스트는 g_로 시작하는 id)
-- private_to: 비밀 메시지를 받는 게스트의 id (비어 있으면 모두에게 보이는 메시지)
alter table public.messages add column if not exists sender_id text;
alter table public.messages add column if not exists private_to text;
update public.messages set sender_id = sender where sender_id is null;

-- 게스트가 만든 개인·단체방
create table if not exists public.rooms (
  id text primary key,
  name text not null,
  owner_id text not null,
  created_at timestamptz not null default now()
);

-- 방 행을 지우면 참여자 목록도 함께 지워진다.
create table if not exists public.room_members (
  room_id text not null references public.rooms (id) on delete cascade,
  uid text not null,
  name text not null,
  primary key (room_id, uid)
);

-- 강퇴(kick)와 채팅 금지(mute). uid는 게스트 쿠키 id, name은 입력한 이름이다.
create table if not exists public.sanctions (
  id bigint generated always as identity primary key,
  uid text not null,
  name text not null,
  kind text not null check (kind in ('kick', 'mute')),
  until timestamptz not null
);

alter table public.rooms enable row level security;
alter table public.room_members enable row level security;
alter table public.sanctions enable row level security;
