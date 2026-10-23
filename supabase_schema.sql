-- 비둘기 서비스 Supabase 설정
-- Supabase 대시보드 → SQL Editor에 붙여 넣고 Run을 한 번 누릅니다.

-- 대화 기록 테이블 (테이블은 이것 하나만 사용)
create table if not exists public.messages (
  id bigint generated always as identity primary key,
  room text not null check (room in ('room1', 'room2')),
  sender text not null check (sender in ('홍록기', '허순태', '곽승현')),
  body text not null default '',
  file_path text,
  file_name text,
  file_type text,
  file_size bigint,
  created_at timestamptz not null default now()
);

create index if not exists messages_room_id_idx on public.messages (room, id);

-- RLS를 켜고 정책을 만들지 않으면 공개(anon) 키로는 아무것도 읽거나 쓸 수 없다.
-- 서버는 secret(service_role) 키로 접근하므로 영향을 받지 않는다.
alter table public.messages enable row level security;

-- 파일 저장용 비공개 버킷 (파일당 20MB)
insert into storage.buckets (id, name, public, file_size_limit)
values ('pigeon-files', 'pigeon-files', false, 20971520)
on conflict (id) do nothing;
