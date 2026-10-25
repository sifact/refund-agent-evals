-- Refund agent schema: profiles, purchases, refund tickets and their items.
--
-- Security model: clients (anon / authenticated) may only READ, and only their
-- own rows unless they are staff. Every write goes through the backend's
-- RefundService using the service connection, so there are deliberately no
-- insert/update/delete policies and those privileges are revoked.

-- ---------------------------------------------------------------- tables

create table public.profiles (
    id uuid primary key references auth.users on delete cascade,
    display_name text not null,
    role text not null default 'customer' check (role in ('customer', 'staff'))
);

create table public.purchases (
    id uuid primary key default gen_random_uuid(),
    customer_id uuid not null references public.profiles,
    item_name text not null,
    price_cents integer not null check (price_cents > 0),
    purchased_on date not null
);

create index purchases_customer_id_idx on public.purchases (customer_id);

create table public.refund_tickets (
    id uuid primary key default gen_random_uuid(),
    customer_id uuid not null references public.profiles,
    status text not null check (status in ('approved', 'pending_review', 'rejected')),
    amount_cents integer not null check (amount_cents >= 0),
    decision_reasons jsonb not null default '{}',
    created_at timestamptz not null default now(),
    reviewed_by uuid references public.profiles,
    reviewed_at timestamptz,
    review_note text
);

-- A customer's history (newest first) and the staff review queue (oldest first).
create index refund_tickets_customer_created_idx
    on public.refund_tickets (customer_id, created_at desc);
create index refund_tickets_status_created_idx
    on public.refund_tickets (status, created_at);

create table public.refund_ticket_items (
    ticket_id uuid references public.refund_tickets on delete cascade,
    purchase_id uuid references public.purchases,
    -- false once the ticket is rejected, which frees the purchase for a new ticket.
    active boolean not null default true,
    -- Keeps the purchase order the customer asked for, so reads round-trip exactly.
    position smallint not null default 0,
    primary key (ticket_id, purchase_id)
);

-- The database-level guarantee against double refunds: a purchase can sit on
-- at most one non-rejected ticket, across all customers.
create unique index refund_ticket_items_active_purchase_uq
    on public.refund_ticket_items (purchase_id) where active;

-- ---------------------------------------------------------------- helpers

-- security definer so policies can check the caller's role without recursing
-- through the profiles RLS policy; empty search_path blocks hijacking.
create function public.is_staff() returns boolean
language sql stable security definer set search_path = ''
as $$
    select exists (
        select 1 from public.profiles where id = auth.uid() and role = 'staff'
    )
$$;

-- ---------------------------------------------------------------- row-level security

alter table public.profiles enable row level security;
alter table public.purchases enable row level security;
alter table public.refund_tickets enable row level security;
alter table public.refund_ticket_items enable row level security;

-- (select auth.uid()) is evaluated once per statement instead of once per row.
create policy profiles_select on public.profiles
    for select to authenticated
    using (id = (select auth.uid()) or public.is_staff());

create policy purchases_select on public.purchases
    for select to authenticated
    using (customer_id = (select auth.uid()) or public.is_staff());

create policy refund_tickets_select on public.refund_tickets
    for select to authenticated
    using (customer_id = (select auth.uid()) or public.is_staff());

create policy refund_ticket_items_select on public.refund_ticket_items
    for select to authenticated
    using (
        exists (
            select 1 from public.refund_tickets t
            where t.id = ticket_id
              and (t.customer_id = (select auth.uid()) or public.is_staff())
        )
    );

-- Belt and braces: even if a write policy were added by mistake, clients still
-- lack the privilege. truncate is included because it bypasses RLS entirely.
revoke insert, update, delete, truncate
    on public.profiles, public.purchases, public.refund_tickets, public.refund_ticket_items
    from anon, authenticated;
