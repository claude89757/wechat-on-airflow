--用户表
CREATE TABLE public.user_profiles (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
  display_name TEXT,
  phone TEXT,
  department TEXT,
  position TEXT,
  avatar_url TEXT,
  bio TEXT,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  CONSTRAINT user_profiles_user_id_key UNIQUE (user_id)
);

-- 创建索引以提高查询性能
CREATE INDEX idx_user_profiles_user_id ON public.user_profiles(user_id);

-- 添加行级安全策略
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;

-- 允许用户读取所有用户配置文件
CREATE POLICY "允许所有用户查看用户配置文件" 
  ON public.user_profiles FOR SELECT 
  USING (true);

-- 用户只能修改自己的配置文件
CREATE POLICY "用户只能修改自己的配置文件" 
  ON public.user_profiles FOR UPDATE 
  USING (auth.uid() = user_id);

-- 用户只能插入自己的配置文件
CREATE POLICY "用户只能插入自己的配置文件" 
  ON public.user_profiles FOR INSERT 
  USING (auth.uid() = user_id);

-- 用户不能删除配置文件（可选）
CREATE POLICY "用户不能删除配置文件" 
  ON public.user_profiles FOR DELETE 
  USING (false);
  
-- 触发器自动更新 updated_at 字段
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_user_profiles_updated_at
BEFORE UPDATE ON public.user_profiles
FOR EACH ROW
EXECUTE FUNCTION update_modified_column();

ALTER TABLE public.user_profiles ADD COLUMN material_list UUID[] DEFAULT '{}';
COMMENT ON COLUMN public.user_profiles.material_list IS 'List of material IDs the user has access to view';

ALTER TABLE public.user_profiles ADD COLUMN industry TEXT DEFAULT '医美';