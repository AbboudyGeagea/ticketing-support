"""Seed hospitals, products, hospital-product links, and LAUMC shared installation

Revision ID: e5f6a7b8c9d0
Revises: d1f2a3b4c5e6
Create Date: 2026-05-23 00:00:00.000000

"""
from alembic import op

revision = 'e5f6a7b8c9d0'
down_revision = 'd1f2a3b4c5e6'
branch_labels = None
depends_on = None


def upgrade():
    # ── Hospitals ─────────────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO hospitals (name, email_domain, address, active, created_at)
        SELECT v.name, v.domain, v.address, TRUE, NOW()
        FROM (VALUES
            ('New Mazloum Hospital', 'newmazloum.com',    'Tripoli, Lebanon'),
            ('CHN',                  'chn.com.lb',         'Zgharta'),
            ('Bekaa Hospital',       'bekaahospital.com',  'Taalabaya, Bekaa'),
            ('Rosaire Hospital',     'hopitalrosaire.org', 'Jemayze, Beirut'),
            ('AUBMC',                'aub.edu.lb',         'Hamra, Beirut'),
            ('LAUMC-RH',             'umcrh.com',          NULL),
            ('LAUMC-SJH',            'laumcsjh.com',       NULL)
        ) AS v(name, domain, address)
        WHERE NOT EXISTS (
            SELECT 1 FROM hospitals WHERE hospitals.name = v.name
        );
    """)

    # ── Products ──────────────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO products (name, active)
        SELECT v.name, TRUE
        FROM (VALUES
            ('VUE PACS'),
            ('Vue Motion'),
            ('My VUE'),
            ('VUE RIS'),
            ('CD Direct'),
            ('CVIS'),
            ('Pyxis'),
            ('RAYD'),
            ('HIS'),
            ('EMR')
        ) AS v(name)
        WHERE NOT EXISTS (
            SELECT 1 FROM products WHERE products.name = v.name
        );
    """)

    # ── Hospital → Product links ───────────────────────────────────────────────

    # AUBMC: Pyxis only
    op.execute("""
        INSERT INTO hospital_products (hospital_id, product_id)
        SELECT h.id, p.id
        FROM hospitals h, products p
        WHERE h.name = 'AUBMC'
          AND p.name = 'Pyxis'
          AND NOT EXISTS (
              SELECT 1 FROM hospital_products hp
              WHERE hp.hospital_id = h.id AND hp.product_id = p.id
          );
    """)

    # LAUMC-RH: VUE PACS, VUE RIS, Vue Motion, My VUE, CD Direct, CVIS, Pyxis
    op.execute("""
        INSERT INTO hospital_products (hospital_id, product_id)
        SELECT h.id, p.id
        FROM hospitals h, products p
        WHERE h.name = 'LAUMC-RH'
          AND p.name IN ('VUE PACS', 'VUE RIS', 'Vue Motion', 'My VUE', 'CD Direct', 'CVIS', 'Pyxis')
          AND NOT EXISTS (
              SELECT 1 FROM hospital_products hp
              WHERE hp.hospital_id = h.id AND hp.product_id = p.id
          );
    """)

    # LAUMC-SJH: same as LAUMC-RH
    op.execute("""
        INSERT INTO hospital_products (hospital_id, product_id)
        SELECT h.id, p.id
        FROM hospitals h, products p
        WHERE h.name = 'LAUMC-SJH'
          AND p.name IN ('VUE PACS', 'VUE RIS', 'Vue Motion', 'My VUE', 'CD Direct', 'CVIS', 'Pyxis')
          AND NOT EXISTS (
              SELECT 1 FROM hospital_products hp
              WHERE hp.hospital_id = h.id AND hp.product_id = p.id
          );
    """)

    # New Mazloum, CHN, Bekaa, Rosaire: VUE PACS, Vue Motion, My VUE, CD Direct
    op.execute("""
        INSERT INTO hospital_products (hospital_id, product_id)
        SELECT h.id, p.id
        FROM hospitals h, products p
        WHERE h.name IN ('New Mazloum Hospital', 'CHN', 'Bekaa Hospital', 'Rosaire Hospital')
          AND p.name IN ('VUE PACS', 'Vue Motion', 'My VUE', 'CD Direct')
          AND NOT EXISTS (
              SELECT 1 FROM hospital_products hp
              WHERE hp.hospital_id = h.id AND hp.product_id = p.id
          );
    """)

    # ── SharedInstallation: LAUMC-RH + LAUMC-SJH ─────────────────────────────
    # One shared installation per shared product, linking both hospitals.
    # The CTE inserts the installation and returns its id so we can link hospitals in the same statement.
    op.execute("""
        WITH new_installations AS (
            INSERT INTO shared_installations (name, product_id, created_at)
            SELECT 'LAUMC - ' || p.name, p.id, NOW()
            FROM products p
            WHERE p.name IN ('VUE PACS', 'VUE RIS', 'Vue Motion', 'My VUE', 'CD Direct', 'CVIS', 'Pyxis')
              AND NOT EXISTS (
                  SELECT 1 FROM shared_installations si
                  WHERE si.product_id = p.id
              )
            RETURNING id
        )
        INSERT INTO shared_installation_hospitals (installation_id, hospital_id)
        SELECT ni.id, h.id
        FROM new_installations ni
        CROSS JOIN hospitals h
        WHERE h.name IN ('LAUMC-RH', 'LAUMC-SJH')
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    # Remove shared installation hospital links for LAUMC
    op.execute("""
        DELETE FROM shared_installation_hospitals
        WHERE installation_id IN (
            SELECT si.id FROM shared_installations si
            WHERE si.name LIKE 'LAUMC - %'
        );
    """)
    op.execute("DELETE FROM shared_installations WHERE name LIKE 'LAUMC - %';")

    # Remove hospital-product links
    op.execute("""
        DELETE FROM hospital_products
        WHERE hospital_id IN (
            SELECT id FROM hospitals
            WHERE name IN ('New Mazloum Hospital','CHN','Bekaa Hospital','Rosaire Hospital','AUBMC','LAUMC-RH','LAUMC-SJH')
        );
    """)

    # Remove products (only if not referenced by tickets)
    op.execute("""
        DELETE FROM products
        WHERE name IN ('VUE PACS','Vue Motion','My VUE','VUE RIS','CD Direct','CVIS','Pyxis','RAYD','HIS','EMR')
          AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.product_id = products.id);
    """)

    # Remove hospitals (only if no tickets)
    op.execute("""
        DELETE FROM hospitals
        WHERE name IN ('New Mazloum Hospital','CHN','Bekaa Hospital','Rosaire Hospital','AUBMC','LAUMC-RH','LAUMC-SJH')
          AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.hospital_id = hospitals.id);
    """)
